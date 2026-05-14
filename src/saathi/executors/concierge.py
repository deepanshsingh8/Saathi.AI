"""Telegram concierge bot.

Day 3: ``notify_deep`` only — used by orchestrator escalation. Day 5 extends
this with ``send_payment_request_to_deep`` + ``handle_deep_confirmation`` for
bill-pay handoff.

httpx-only (no python-telegram-bot SDK weight) — Telegram bot API is REST.
"""
from __future__ import annotations

from typing import Literal

import httpx

from saathi.config import Settings, get_settings
from saathi.utils.logging import get_logger

log = get_logger(__name__)

Severity = Literal["info", "warning", "blocked"]
TG_BASE = "https://api.telegram.org"
DEFAULT_TIMEOUT = httpx.Timeout(10.0)


class ConciergeError(RuntimeError):
    """Raised when Telegram returns a non-2xx or unexpected payload."""


async def notify_deep(
    severity: Severity,
    message: str,
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> int:
    """Post a message to Deep's Telegram chat. Returns the Telegram message_id.

    Severity prefix lets Deep filter at a glance (push notifications include it).
    """
    s = settings or get_settings()
    if not s.TELEGRAM_BOT_TOKEN or not s.TELEGRAM_DEEP_CHAT_ID:
        log.warning("notify_deep_misconfigured")
        raise ConciergeError("telegram bot not configured")

    prefix = {"info": "ℹ️", "warning": "⚠️", "blocked": "🚨"}[severity]
    text = f"{prefix} <b>Saathi {severity}</b>\n{message}"

    url = f"{TG_BASE}/bot{s.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": s.TELEGRAM_DEEP_CHAT_ID, "text": text, "parse_mode": "HTML"}

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
    try:
        resp = await http.post(url, json=payload)
    finally:
        if owns_client:
            await http.aclose()

    if resp.status_code >= 300:
        raise ConciergeError(f"telegram error {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    if not data.get("ok"):
        raise ConciergeError(f"telegram not-ok: {data}")
    msg_id = data["result"]["message_id"]
    log.info("concierge_notified", severity=severity, msg_id=msg_id)
    return msg_id


# ─── Day 5 — bill-pay handoff ────────────────────────────────────────────────


async def send_payment_request_to_deep(
    *,
    bill: dict,
    confirmation_token: str,
    mom_callback: str,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> int:
    """Telegram message to Deep with bill summary + inline buttons + payment link.

    Persists the pending bill to DDB (TTL 1h) so the inbound webhook can resume
    the flow. Inline buttons carry ``paid:<token>`` / ``skip:<token>`` callback
    data; the orchestrator's ``/telegram/webhook`` route resolves them.
    """
    s = settings or get_settings()
    if not s.TELEGRAM_BOT_TOKEN or not s.TELEGRAM_DEEP_CHAT_ID:
        raise ConciergeError("telegram bot not configured")

    # Lazy import to avoid the orchestrator <-> dynamo cycle at import time.
    from saathi.storage import dynamo

    await dynamo.put_pending_bill(
        confirmation_token,
        {"bill": bill, "mom_callback": mom_callback},
    )

    rupees = bill.get("amount_paise", 0) // 100
    text = (
        f"💸 <b>Saathi bill payment</b>\n"
        f"Utility: {bill.get('utility')}\n"
        f"Amount: ₹{rupees:,}\n"
        f"Due: {bill.get('due_date', '—')}\n"
        f"Consumer #: {bill.get('consumer_number', '—')}\n"
        f"Token: <code>{confirmation_token}</code>\n\n"
        f"<a href=\"{bill.get('payment_url', '')}\">Open payment page</a>\n"
        f"Tip: reply to this message with the receipt screenshot to forward to Mom."
    )
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Mark Paid", "callback_data": f"paid:{confirmation_token}"},
            {"text": "❌ Skip", "callback_data": f"skip:{confirmation_token}"},
        ]]
    }

    url = f"{TG_BASE}/bot{s.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": s.TELEGRAM_DEEP_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": keyboard,
    }

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
    try:
        resp = await http.post(url, json=payload)
    finally:
        if owns_client:
            await http.aclose()
    if resp.status_code >= 300:
        raise ConciergeError(f"telegram error {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if not data.get("ok"):
        raise ConciergeError(f"telegram not-ok: {data}")
    msg_id = data["result"]["message_id"]
    log.info("concierge_payment_request_sent", msg_id=msg_id, token=confirmation_token)

    # Schedule the 10-min mom-nudge + 1-hr deep-escalate. Cancelled on success.
    from saathi import scheduler
    scheduler.schedule_nudges(sender=mom_callback, token=confirmation_token, settings=s)

    return msg_id


async def fetch_telegram_photo_url(
    *,
    file_id: str,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Resolve a Telegram ``file_id`` (from a photo update) into a public URL.

    Telegram returns ``{"file_path": "..."}``; the public URL is
    ``https://api.telegram.org/file/bot<TOKEN>/<file_path>`` and is valid for
    ~1 hour. WhatsApp can fetch this directly via the ``link`` field of an
    image message — no need to re-host on S3.
    """
    s = settings or get_settings()
    if not s.TELEGRAM_BOT_TOKEN:
        raise ConciergeError("telegram bot not configured")
    url = f"{TG_BASE}/bot{s.TELEGRAM_BOT_TOKEN}/getFile"

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
    try:
        resp = await http.post(url, json={"file_id": file_id})
    finally:
        if owns_client:
            await http.aclose()
    if resp.status_code >= 300:
        raise ConciergeError(f"telegram getFile {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if not data.get("ok"):
        raise ConciergeError(f"telegram getFile not-ok: {data}")
    file_path = data["result"]["file_path"]
    return f"{TG_BASE}/file/bot{s.TELEGRAM_BOT_TOKEN}/{file_path}"


async def handle_deep_confirmation(
    *,
    token: str,
    paid: bool,
    receipt_image_id: str | None = None,
    settings: Settings | None = None,
) -> dict:
    """Called by the Telegram webhook when Deep taps an inline button.

    On ``paid``: voice-confirm to Mom + forward receipt image (if provided).
    On ``skip``: voice-apologise; flag for retry.
    """
    s = settings or get_settings()
    from saathi.messaging import whatsapp
    from saathi.speech import sarvam
    from saathi.storage import dynamo

    pending = await dynamo.get_pending_bill(token)
    if pending is None:
        log.warning("deep_confirmation_no_pending", token=token)
        return {"status": "no_pending"}

    sender = pending.get("mom_callback", "")
    bill = pending.get("bill", {})

    if paid:
        rupees = bill.get("amount_paise", 0) // 100
        from saathi.utils.hindi import rupees_to_hindi_words
        text = (
            f"मम्मी, {bill.get('utility', 'बिल')} का {rupees_to_hindi_words(rupees)} भर दिया है।"
        )
        try:
            audio = await sarvam.synthesize(text, settings=s)
            media_id = await whatsapp.upload_media(audio, "audio/mpeg", settings=s)
            await whatsapp.send_audio(sender, media_id, settings=s)
            if receipt_image_id:
                # Resolve Telegram file_id → public URL → forward as WA image.
                try:
                    photo_url = await fetch_telegram_photo_url(
                        file_id=receipt_image_id, settings=s,
                    )
                    await whatsapp.send_image(
                        sender, link=photo_url,
                        caption="रसीद / receipt", settings=s,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("receipt_forward_failed", err=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.warning("paid_ack_failed", err=str(exc))
    else:
        try:
            audio = await sarvam.synthesize(
                "मम्मी, अभी payment नहीं हो पाया, कल हो जाएगा।", settings=s,
            )
            media_id = await whatsapp.upload_media(audio, "audio/mpeg", settings=s)
            await whatsapp.send_audio(sender, media_id, settings=s)
        except Exception as exc:  # noqa: BLE001
            log.warning("skip_ack_failed", err=str(exc))

    await dynamo.delete_pending_bill(token)
    # Cancel the scheduled nudges — Deep resolved (paid or explicitly skipped).
    from saathi import scheduler
    scheduler.cancel_nudges(token)
    return {"status": "paid" if paid else "skipped"}
