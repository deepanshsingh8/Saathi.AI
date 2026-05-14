"""Saathi FastAPI app.

Routes:
- GET  /healthz  → Lightsail/Caddy health check
- GET  /webhook  → Meta verification handshake
- POST /webhook  → inbound message dispatch (HMAC-verified, mom-only)
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request, Response

from saathi import lifecycle
from saathi.config import Settings, get_settings
from saathi.executors import concierge
from saathi.llm import abort as abort_mod
from saathi.llm import intent as intent_mod
from saathi.llm import orchestrator
from saathi.messaging import templates, webhooks, whatsapp
from saathi.speech import sarvam
from saathi.storage import dynamo, s3
from saathi.utils.logging import get_logger

log = get_logger(__name__)

GREETING_HI = "नमस्ते मम्मी, मैं Saathi बोल रही हूँ"

@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Spawn the Sarvam keepalive cron at startup. Browserbase pre-warm fires
    lazily (per-intent) from handle_voice_turn — no startup hook needed."""
    lifecycle.start_sarvam_keepalive()
    try:
        yield
    finally:
        lifecycle.stop_sarvam_keepalive()


app = FastAPI(title="Saathi", version="0.1.0", lifespan=_lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"ok": True, "service": "saathi"}


@app.get("/webhook")
async def webhook_verify(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
) -> Response:
    """Meta calls this once when the webhook is configured.

    On match, return the int(challenge) as a plain text body so Meta accepts it.
    """
    s = get_settings()
    if hub_mode == "subscribe" and hub_verify_token == s.WA_VERIFY_TOKEN:
        return Response(content=str(int(hub_challenge)), media_type="text/plain")
    log.warning("webhook_verify_rejected", mode=hub_mode)
    raise HTTPException(status_code=403, detail="verify token mismatch")


@app.post("/webhook")
async def webhook_inbound(
    request: Request,
    bg: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> dict[str, Any]:
    """Inbound Cloud API events.

    1. HMAC-verify the raw body. 401 on mismatch.
    2. Extract message; ignore status updates (return 200).
    3. Drop messages from non-mom senders silently (200 + log).
    4. Dispatch text messages to background echo handler so we ack <20s.
    """
    s = get_settings()
    body = await request.body()
    if not webhooks.verify_signature(body, x_hub_signature_256, s.WA_APP_SECRET):
        log.warning("webhook_bad_signature")
        raise HTTPException(status_code=401, detail="bad signature")

    payload = await request.json()
    msg = webhooks.extract_message(payload)
    if msg is None:
        # Likely a status update (delivered/read). Ignore.
        return {"ok": True}

    sender = msg.get("from", "")
    if sender != _normalize(s.WA_MOM_NUMBER):
        log.warning("webhook_dropped_sender", sender=_mask(sender))
        return {"ok": True}

    msg_type = msg.get("type")
    if msg_type == "text":
        bg.add_task(handle_text_message, msg, settings=s)
    elif msg_type == "audio":
        bg.add_task(handle_audio_message, msg, settings=s)
    elif msg_type == "interactive":
        bg.add_task(handle_interactive_message, msg, settings=s)
    else:
        log.info("webhook_unhandled_type", msg_type=msg_type)

    return {"ok": True}


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    bg: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Telegram bot webhook for Deep's concierge confirmations.

    Verifies the secret token Telegram echoes back, ensures the chat_id
    belongs to Deep, and dispatches paid/skip callbacks.
    """
    s = get_settings()
    if not s.TELEGRAM_WEBHOOK_SECRET or x_telegram_bot_api_secret_token != s.TELEGRAM_WEBHOOK_SECRET:
        log.warning("telegram_bad_secret")
        raise HTTPException(status_code=401, detail="bad telegram secret")

    update = await request.json()

    # Inbound photo (Deep replies with receipt screenshot to a Saathi
    # payment-request message). We treat it as confirmation for the token
    # embedded in the reply-to message text.
    message = update.get("message")
    if message and message.get("photo"):
        msg_chat = str(message.get("chat", {}).get("id", ""))
        if msg_chat != s.TELEGRAM_DEEP_CHAT_ID:
            return {"ok": True}
        token = _extract_token_from_reply(message.get("reply_to_message", {}))
        if not token:
            log.warning("telegram_photo_no_token")
            return {"ok": True}
        # Largest photo size is the last entry.
        photo_id = message["photo"][-1]["file_id"]
        bg.add_task(
            concierge.handle_deep_confirmation,
            token=token, paid=True, receipt_image_id=photo_id, settings=s,
        )
        return {"ok": True}

    callback = update.get("callback_query")
    if callback is None:
        # Other update types (free-text messages from Deep) — ignored for v1.
        return {"ok": True}

    chat_id = str(callback.get("from", {}).get("id", ""))
    if chat_id != s.TELEGRAM_DEEP_CHAT_ID:
        log.warning("telegram_unauthorized_chat", chat_id=chat_id)
        return {"ok": True}  # silently drop, never 401 to Telegram

    data = callback.get("data", "")
    if ":" not in data:
        return {"ok": True}
    action, _, token = data.partition(":")
    paid = action == "paid"

    bg.add_task(concierge.handle_deep_confirmation, token=token, paid=paid, settings=s)
    return {"ok": True}


def _extract_token_from_reply(reply_msg: dict[str, Any]) -> str | None:
    """The original Saathi payment-request message contains
    ``"Token: <hex>"`` in its body. Pull the hex out so a photo reply can be
    matched to its pending bill.

    Falls back to scanning the visible text for any 32-hex sequence.
    """
    text = (reply_msg.get("text") or reply_msg.get("caption") or "")
    import re
    m = re.search(r"\b([a-f0-9]{32})\b", text)
    return m.group(1) if m else None


async def handle_text_message(msg: dict[str, Any], *, settings: Settings | None = None) -> None:
    """Day 1 echo: reply with the canned Hindi greeting."""
    s = settings or get_settings()
    sender = msg["from"]
    log.info("text_in", sender=_mask(sender), len=len(msg.get("text", {}).get("body", "")))
    try:
        wamid = await whatsapp.send_text(sender, GREETING_HI, settings=s)
    except whatsapp.WhatsAppError as exc:
        log.warning("echo_send_failed", err=str(exc))
        return
    log.info("echo_sent", wamid=wamid)


async def handle_audio_message(msg: dict[str, Any], *, settings: Settings | None = None) -> None:
    """Day 2 voice round-trip: download → archive → STT → echo TTS → send_audio.

    RE-VALIDATE end-to-end once a real Sarvam key + S3 bucket are live. The pipeline
    is unit-tested but the latency budget (P50 < 5s) is only meaningful in prod.
    """
    s = settings or get_settings()
    sender = msg["from"]
    media_id = msg.get("audio", {}).get("id")
    if not media_id:
        log.warning("audio_msg_missing_id")
        return

    conv_id = f"{sender}-{int(time.time())}"
    started = time.monotonic()

    try:
        audio_in, mime = await whatsapp.download_media(media_id, settings=s)
    except whatsapp.WhatsAppError as exc:
        log.warning("audio_download_failed", err=str(exc), conv_id=conv_id)
        return

    # Fire-and-forget archive — don't let S3 latency block the reply.
    asyncio.create_task(_archive_inbound(audio_in, conv_id))

    # Day 6 polish 1 — fire interim ack BEFORE STT so Mom hears something
    # within ~2s. Random pick from cached pool; falls back to live Sarvam if
    # cache miss (slower, but the prerender script may not have been run yet).
    asyncio.create_task(_send_interim_ack(sender=sender, settings=s, conv_id=conv_id))

    try:
        transcript = await sarvam.transcribe(audio_in, mode=s.STT_MODE, settings=s)  # type: ignore[arg-type]
    except sarvam.SarvamError as exc:
        log.warning("stt_failed", err=str(exc), conv_id=conv_id)
        return
    log.info("stt_done", conv_id=conv_id, latency_ms=int((time.monotonic() - started) * 1000),
             transcript_len=len(transcript))

    if not transcript:
        log.info("stt_empty_transcript", conv_id=conv_id)
        return

    log.info("stt_done_routing", conv_id=conv_id, transcript_len=len(transcript))

    # Day 6 polish 3: stop-keyword pre-check. If Mom said "रोको" / "cancel" at
    # the start of this voice note, set the abort flag on her current session
    # BEFORE the regular intent classifier runs.
    if abort_mod.is_stop_command(transcript):
        prev_conv_id = _LATEST_PTR.get("conv_id")
        if prev_conv_id:
            try:
                await dynamo.set_abort_flag("mom", prev_conv_id, value=True)
                log.info("abort_flag_set", conv_id=prev_conv_id)
            except Exception as exc:  # noqa: BLE001
                log.warning("abort_flag_set_failed", err=str(exc))
        # Send Mom an immediate ack — no LLM call needed.
        await _send_failure_voice("generic", sender=sender, settings=s,
                                   override_text="ठीक है मम्मी, रोक दिया।")
        return

    _LATEST_PTR["conv_id"] = conv_id

    # Day 3+: route into intent classifier + orchestrator. The orchestrator
    # owns voice replies via the speak_to_mom tool — we do not echo here.
    await handle_voice_turn(transcript, sender=sender, settings=s)
    log.info("voice_turn_done", conv_id=conv_id,
             total_ms=int((time.monotonic() - started) * 1000), inbound_mime=mime)


async def _send_failure_voice(
    key: str, *, sender: str, settings: Settings,
    override_text: str | None = None, **fmt: str,
) -> None:
    """Send a pre-rendered Hindi failure voice to Mom.

    Tries the DDB media_id cache first (Day 6 polish 4). Falls back to live
    Sarvam synthesis if cache miss — slower but still keeps Mom in Hindi.
    """
    try:
        cached = await dynamo.get_session_state("mom", f"system_voice#{key}")
    except Exception:  # noqa: BLE001
        cached = None
    if cached and cached.get("media_id"):
        try:
            await whatsapp.send_audio(sender, cached["media_id"], settings=settings)
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("cached_voice_send_failed", err=str(exc), key=key)

    text = override_text or templates.failure_voice(key, **fmt)
    try:
        audio = await sarvam.synthesize(text, settings=settings)
        media_id = await whatsapp.upload_media(audio, "audio/mpeg", settings=settings)
        await whatsapp.send_audio(sender, media_id, settings=settings)
    except Exception as exc:  # noqa: BLE001
        log.warning("failure_voice_failed", err=str(exc), key=key)


async def _archive_inbound(data: bytes, conv_id: str) -> None:
    """Best-effort S3 archival; failures don't block the reply path."""
    try:
        await s3.put_voice("mom", "inbound", data, ext="oga")
    except Exception as exc:  # noqa: BLE001
        log.warning("s3_archive_failed", err=str(exc), conv_id=conv_id)


async def _send_interim_ack(*, sender: str, settings: Settings, conv_id: str) -> None:
    """Day 6 polish 1: send a pre-cached interim ack within ~2s of voice arrival.

    Picks a random key from the cached pool (system_voice#interim:N). On cache
    miss (no media_id in DDB), falls back to live Sarvam — slower (~1s), but
    we still want Mom to hear acknowledgment.
    """
    import random as _random
    idx = _random.randrange(len(templates.INTERIM_ACKS))
    cache_key = f"interim:{idx}"
    try:
        cached = await dynamo.get_session_state("mom", f"system_voice#{cache_key}")
    except Exception:  # noqa: BLE001
        cached = None
    if cached and cached.get("media_id"):
        try:
            await whatsapp.send_audio(sender, cached["media_id"], settings=settings)
            log.info("interim_ack_sent_cached", conv_id=conv_id, key=cache_key)
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("interim_ack_cached_failed", err=str(exc), key=cache_key)

    # Cache miss — synthesize live. Cheap enough; not the hot path long-term.
    try:
        text = templates.INTERIM_ACKS[idx]
        audio = await sarvam.synthesize(text, settings=settings)
        media_id = await whatsapp.upload_media(audio, "audio/mpeg", settings=settings)
        await whatsapp.send_audio(sender, media_id, settings=settings)
        log.info("interim_ack_sent_live", conv_id=conv_id, key=cache_key)
    except Exception as exc:  # noqa: BLE001
        log.warning("interim_ack_live_failed", err=str(exc), key=cache_key)


# ──────────────────────────────────────────────────────────────────────────────
# Day 3+ — full voice → intent → orchestrator → tools loop
# ──────────────────────────────────────────────────────────────────────────────


async def handle_voice_turn(transcript: str, *, sender: str, settings: Settings) -> None:
    """Day 3 entry: classify intent, route into orchestrator.

    For Day 2 echo-only behavior, leave ``handle_audio_message`` as-is. This
    function is wired in only when the LLM credentials are present (Day 3+).
    """
    conv_id = f"{sender}-{int(time.time())}"
    intent = await intent_mod.classify(transcript, settings=settings)

    # Day 6 polish 7: pre-warm a Browserbase session in parallel with the LLM
    # turn so the executor doesn't pay session-create cold start.
    lifecycle.maybe_prewarm_browserbase(intent["intent"], settings=settings)

    if intent["intent"] == "chitchat":
        # Cheap pre-canned greeting, no orchestrator call needed.
        try:
            audio = await sarvam.synthesize(
                "नमस्ते मम्मी, मैं Saathi बोल रही हूँ — कुछ मंगवाना है?", settings=settings,
            )
            media_id = await whatsapp.upload_media(audio, "audio/mpeg", settings=settings)
            await whatsapp.send_audio(sender, media_id, settings=settings)
        except Exception as exc:  # noqa: BLE001
            log.warning("chitchat_reply_failed", err=str(exc))
        return
    if intent["intent"] == "unknown":
        try:
            audio = await sarvam.synthesize(
                "मम्मी, समझ नहीं आया, एक बार और बोलिए?", settings=settings,
            )
            media_id = await whatsapp.upload_media(audio, "audio/mpeg", settings=settings)
            await whatsapp.send_audio(sender, media_id, settings=settings)
        except Exception as exc:  # noqa: BLE001
            log.warning("unknown_reply_failed", err=str(exc))
        return

    await orchestrator.run_turn(
        transcript, sender=sender, conv_id=conv_id, intent=intent, settings=settings,
    )


async def handle_interactive_message(
    msg: dict[str, Any], *, settings: Settings | None = None,
) -> None:
    """Mom tapped a reply button. Resume the paused agent loop."""
    s = settings or get_settings()
    sender = msg["from"]
    interactive = msg.get("interactive", {})
    button_reply = interactive.get("button_reply", {})
    button_id = button_reply.get("id", "")
    button_title = button_reply.get("title", "")
    if not button_id:
        log.warning("interactive_no_button_id")
        return

    # The latest open session for Mom — derived from sender + most recent timestamp.
    # For v1 we look up by an in-memory pointer (single user, single concurrent
    # session). DDB single-user means we can scan sessions cheaply.
    conv_id = await _latest_conv_id(sender)
    if not conv_id:
        log.warning("no_conv_id_for_button")
        return

    await orchestrator.resume_after_button(
        sender=sender, conv_id=conv_id,
        button_id=button_id, button_title=button_title, settings=s,
    )


async def _latest_conv_id(sender: str) -> str | None:
    """Find the most recently updated session for ``sender``. Single-user means
    we can cheaply assume Mom has at most one in-flight conversation."""
    from saathi.storage import dynamo
    try:
        # Reuse dynamo's session helper — for v1 we just track the last conv_id
        # the orchestrator persisted. A more durable lookup would query the
        # session-prefix items; in-memory pointer is good enough for single user.
        item = await dynamo.get_session_state("mom", _LATEST_PTR.get("conv_id", ""))
        return item.get("sk", "").split("#", 1)[-1] if item else None
    except Exception:  # noqa: BLE001
        return _LATEST_PTR.get("conv_id")


_LATEST_PTR: dict[str, str] = {}


def _normalize(number: str) -> str:
    """Cloud API surfaces numbers without the leading '+'. Normalize for compare."""
    return number.lstrip("+")


def _mask(num: str) -> str:
    if len(num) <= 6:
        return num
    return f"{num[:4]}…{num[-2:]}"
