"""Saathi orchestrator — Sonnet 4.6 via Bedrock with manual tool-use loop.

Why not claude-agent-sdk? The SDK 0.1.x spawns the Claude Code CLI as a
subprocess (`cli_path`, `add_dirs`). For a server agent that calls custom
Python tools, direct ``anthropic`` SDK with a manual loop is more predictable,
easier to test, and has fewer surface-area surprises. See
``docs/DECISIONS.md`` ``2026-05-14 · Orchestrator: anthropic SDK direct``.

Loop shape:
    1. Build messages = [user_transcript].
    2. Call Sonnet with system_prompt + allowed_tools.
    3. For each tool_use in the assistant turn, dispatch to the Python impl,
       append the tool_result back to messages.
    4. Repeat until stop_reason == "end_turn" or "speak_to_mom with buttons"
       (which we treat as "wait for button"), or max_turns hit.
    5. Persist pending session state to DDB if waiting on a button.

Resume pattern:
    On inbound button reply:
    - Load session#<conv_id> from DDB.
    - Append the button choice as a user turn.
    - Resume the loop.

# RE-VALIDATE prompt-cache header shape and tool_use parsing once first real
# Bedrock turn runs — the response shape is documented but I haven't run it
# against ``ap-south-1`` yet. Day 7 polish.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from anthropic import AsyncAnthropic, AsyncAnthropicBedrock

from saathi.config import Settings, get_settings
from saathi.executors import concierge
from saathi.llm import prompts as P
from saathi.llm import tools as T
from saathi.messaging import whatsapp
from saathi.speech import sarvam
from saathi.storage import dynamo
from saathi.utils.logging import get_logger

log = get_logger(__name__)

ToolImpl = Callable[..., Awaitable[Any]]


class AbortedByUser(Exception):
    """Raised inside a tool dispatch when Mom's session has the abort flag set
    (Day 6 polish 3). Orchestrator catches and exits cleanly."""


class OrchestratorError(RuntimeError):
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Tool implementations
# ──────────────────────────────────────────────────────────────────────────────


async def _tool_speak_to_mom(
    *, sender: str, settings: Settings, conv_id: str, text: str, buttons: list[str] | None = None
) -> dict[str, Any]:
    """Send a Hindi voice message to Mom. If buttons are provided, send the voice
    plus an interactive button message, then return a sentinel telling the
    orchestrator to pause and wait for the button tap.
    """
    audio = await sarvam.synthesize(text, settings=settings)
    media_id = await whatsapp.upload_media(audio, "audio/mpeg", settings=settings)
    voice_wamid = await whatsapp.send_audio(sender, media_id, settings=settings)

    btn_wamid: str | None = None
    if buttons:
        btn_wamid = await whatsapp.send_buttons(
            sender, body="कृपया चुनिए:", buttons=buttons, settings=settings
        )

    return {
        "voice_wamid": voice_wamid,
        "buttons_wamid": btn_wamid,
        "waiting_for_user": bool(buttons),
    }


async def _tool_notify_deep(*, severity: str, message: str, settings: Settings, **_: Any) -> dict[str, Any]:
    msg_id = await concierge.notify_deep(severity, message, settings=settings)  # type: ignore[arg-type]
    return {"telegram_msg_id": msg_id}


CONFIDENCE_THRESHOLD = 0.85
HIGH_STAKES_TOOLS = frozenset({
    "place_medicine_order", "place_grocery_order", "request_payment_via_deep",
})


async def _tool_confirm_understanding(
    *, summary: str, confidence: float, _state: dict, **_: Any,
) -> dict[str, Any]:
    """Day 6 gate. Stores the most recent confidence on the session; subsequent
    high-stakes tool calls check it and refuse if below threshold."""
    _state["last_confidence"] = float(confidence)
    _state["last_summary"] = summary
    return {"summary": summary, "confidence": confidence,
            "threshold": CONFIDENCE_THRESHOLD,
            "passes_gate": float(confidence) >= CONFIDENCE_THRESHOLD}


# Executor wrappers — late-imported to keep this file's import graph lean and
# to allow tests to patch each module independently.

async def _tool_search_medicine(*, query: str, settings: Settings, **_: Any) -> Any:
    from saathi.executors import medicine_1mg
    return await medicine_1mg.search_medicine(query, settings=settings)


def _check_confidence_gate(tool_name: str, state: dict[str, Any]) -> None:
    """Day 6 polish 6: refuse high-stakes tool calls if confirm_understanding
    hasn't fired with confidence ≥ threshold this turn.

    Raises OrchestratorError with a Sonnet-readable instruction. The orchestrator
    threads the error back as a tool_result so Sonnet sees what to do next.
    """
    if tool_name not in HIGH_STAKES_TOOLS:
        return
    conf = state.get("last_confidence", 0.0)
    if conf < CONFIDENCE_THRESHOLD:
        raise OrchestratorError(
            f"confidence_gate: confidence {conf:.2f} < {CONFIDENCE_THRESHOLD}; "
            f"call confirm_understanding first, then re-confirm with Mom via "
            f"speak_to_mom buttons before re-attempting {tool_name}."
        )


async def _tool_place_medicine_order(
    *, sku: str, quantity: int, prescription_s3_uri: str, settings: Settings, _state: dict, **__: Any
) -> Any:
    """Hard guard: refuse SKUs not in the last search_medicine result set."""
    _check_confidence_gate("place_medicine_order", _state)
    last_skus = _state.get("last_medicine_skus", [])
    if last_skus and sku not in last_skus:
        raise OrchestratorError(f"sku {sku!r} not in last search_medicine results")
    from saathi.executors import medicine_1mg
    return await medicine_1mg.place_medicine_order(
        sku, quantity, prescription_s3_uri, settings=settings
    )


# Path A/B grocery dispatch (Gap 5): pick Swiggy MCP if env-enabled, else
# Blinkit Playwright. Decided per-call so a config change doesn't need a
# code redeploy.

def _grocery_executor(settings: Settings):
    from saathi.executors import grocery_blinkit, grocery_swiggy
    return grocery_swiggy if grocery_swiggy.is_enabled(settings) else grocery_blinkit


async def _tool_search_grocery(*, query: str, settings: Settings, **_: Any) -> Any:
    ex = _grocery_executor(settings)
    if hasattr(ex, "search_instamart"):
        from saathi.config import get_settings as _gs
        s = settings or _gs()
        return await ex.search_instamart(query, lat=26.9124, lng=75.7873, settings=s)  # Jaipur
    return await ex.search_blinkit(query, settings=settings)


async def _tool_add_grocery_to_cart(
    *, sku: str, quantity: int, settings: Settings, _state: dict, **_: Any,
) -> Any:
    ex = _grocery_executor(settings)
    if hasattr(ex, "get_or_build_cart"):
        return await ex.get_or_build_cart([sku], settings=settings)
    return await ex.add_to_cart(sku, quantity, settings=settings)


async def _tool_get_grocery_cart(*, settings: Settings, **_: Any) -> Any:
    ex = _grocery_executor(settings)
    if hasattr(ex, "get_or_build_cart"):
        return await ex.get_or_build_cart([], settings=settings)
    return await ex.get_cart(settings=settings)


async def _tool_place_grocery_order(
    *, settings: Settings, _state: dict, **_: Any,
) -> Any:
    _check_confidence_gate("place_grocery_order", _state)
    ex = _grocery_executor(settings)
    if hasattr(ex, "place_instamart_order"):
        cart = _state.get("cart_id", "")
        addr = _state.get("address_id", "")
        return await ex.place_instamart_order(cart, addr, settings=settings)
    return await ex.checkout_cod(settings=settings)


async def _tool_fetch_bill(*, utility: str, settings: Settings, _state: dict, **__: Any) -> Any:
    from saathi.executors import bill_jvvnl
    profile = _state.get("profile", {})
    consumer_number = profile.get("billers", {}).get("electricity", {}).get("consumer_number", "")
    if utility == "electricity":
        if not consumer_number:
            raise OrchestratorError("no electricity consumer_number in profile")
        return await bill_jvvnl.fetch_jvvnl_bill(consumer_number, settings=settings)
    raise OrchestratorError(f"utility {utility!r} not supported in v1")


async def _tool_request_payment_via_deep(
    *, utility: str, amount_paise: int, payment_url: str,
    settings: Settings, _state: dict,
    due_date: str = "", consumer_number: str = "", **__: Any
) -> Any:
    _check_confidence_gate("request_payment_via_deep", _state)
    from saathi.executors import concierge as concierge_full
    token = uuid.uuid4().hex
    bill = {
        "utility": utility,
        "amount_paise": amount_paise,
        "due_date": due_date,
        "consumer_number": consumer_number,
        "payment_url": payment_url,
    }
    msg_id = await concierge_full.send_payment_request_to_deep(
        bill=bill,
        confirmation_token=token,
        mom_callback=_state.get("sender", ""),
        settings=settings,
    )
    return {"telegram_msg_id": msg_id, "token": token}


TOOL_IMPL: dict[str, ToolImpl] = {
    "speak_to_mom": _tool_speak_to_mom,
    "notify_deep": _tool_notify_deep,
    "confirm_understanding": _tool_confirm_understanding,
    "search_medicine": _tool_search_medicine,
    "place_medicine_order": _tool_place_medicine_order,
    "search_grocery": _tool_search_grocery,
    "add_grocery_to_cart": _tool_add_grocery_to_cart,
    "get_grocery_cart": _tool_get_grocery_cart,
    "place_grocery_order": _tool_place_grocery_order,
    "fetch_bill": _tool_fetch_bill,
    "request_payment_via_deep": _tool_request_payment_via_deep,
}


# ──────────────────────────────────────────────────────────────────────────────
# Anthropic client
# ──────────────────────────────────────────────────────────────────────────────


_anthropic: AsyncAnthropic | AsyncAnthropicBedrock | None = None


def _client(settings: Settings) -> AsyncAnthropic | AsyncAnthropicBedrock:
    global _anthropic
    if _anthropic is None:
        if settings.USE_BEDROCK:
            _anthropic = AsyncAnthropicBedrock(aws_region=settings.AWS_REGION)
        else:
            _anthropic = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _anthropic


# ──────────────────────────────────────────────────────────────────────────────
# Loop
# ──────────────────────────────────────────────────────────────────────────────


def _system_for(intent: str, profile: dict, medicines: list[dict], usual_basket: list[dict]) -> str:
    profile_json = json.dumps({k: v for k, v in profile.items() if k not in {"pk", "sk"}},
                              ensure_ascii=False)
    if intent == "medicine":
        return P.MEDICINE_SUBAGENT.format(
            profile_json=profile_json,
            medicines_json=json.dumps(medicines, ensure_ascii=False),
        )
    if intent == "grocery":
        return P.GROCERY_SUBAGENT.format(
            profile_json=profile_json,
            usual_basket_json=json.dumps(usual_basket, ensure_ascii=False),
        )
    if intent == "bill":
        billers = profile.get("billers", {})
        return P.BILL_SUBAGENT.format(
            profile_json=profile_json,
            billers_json=json.dumps(billers, ensure_ascii=False),
        )
    return P.SAATHI_SYSTEM


async def run_turn(
    transcript: str,
    *,
    sender: str,
    conv_id: str,
    intent: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Single conversation turn.

    Returns ``{"status": "done"|"awaiting_user"|"aborted"|"failed", ...}``. The
    caller (FastAPI handler) doesn't need to do anything with the result —
    side effects (voice replies, button messages, orders) all happen inside the
    loop. The return value is for logging and tests.
    """
    s = settings or get_settings()

    # Profile and per-intent context (cached across turns once Bedrock prompt
    # caching is wired — Day 6 polish 7).
    profile = await dynamo.get_profile("mom")
    medicines = await dynamo.list_medicines("mom") if intent["intent"] == "medicine" else []
    usual_basket = (
        (await dynamo.get_usual_basket("mom")).get("items", [])
        if intent["intent"] == "grocery" else []
    )

    state: dict[str, Any] = {
        "sender": sender,
        "conv_id": conv_id,
        "intent": intent,
        "profile": profile,
        "last_medicine_skus": [],
        "last_speak_to_mom": None,
        "started_at": int(time.time() * 1000),
    }

    system = _system_for(intent["intent"], profile, medicines, usual_basket)
    tools = T.tools_for(intent["intent"])
    messages: list[dict[str, Any]] = [{"role": "user", "content": transcript}]

    client = _client(s)
    model = s.BEDROCK_MODEL_SONNET if s.USE_BEDROCK else "claude-sonnet-4-6"

    for turn in range(s.LLM_MAX_TURNS):
        try:
            resp = await client.messages.create(
                model=model,
                max_tokens=2048,
                system=system,
                tools=tools,  # type: ignore[arg-type]
                messages=messages,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("llm_call_failed", err=str(exc), conv_id=conv_id, turn=turn)
            return {"status": "failed", "reason": "llm_call_failed", "err": str(exc)}

        # Append the assistant turn (tool_use blocks + text) verbatim.
        assistant_blocks = [_block_to_dict(b) for b in resp.content]
        messages.append({"role": "assistant", "content": assistant_blocks})

        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        if not tool_uses:
            log.info("orchestrator_done_no_tools", conv_id=conv_id, turns=turn + 1)
            await _persist_done(s, conv_id, state, status="done")
            return {"status": "done", "turns": turn + 1}

        # Execute each tool call; thread results back as tool_result blocks.
        tool_results: list[dict[str, Any]] = []
        wait_for_user = False
        for tu in tool_uses:
            name = tu.name
            inp = dict(tu.input or {})
            impl = TOOL_IMPL.get(name)
            if impl is None:
                tool_results.append(_tool_result(tu.id, {"error": f"unknown tool {name}"}, is_error=True))
                continue

            # Check abort flag right before any tool dispatch.
            if await _is_aborted(s, conv_id):
                log.info("orchestrator_aborted", conv_id=conv_id)
                await _send_abort_ack(s, sender)
                return {"status": "aborted"}

            try:
                result = await impl(sender=sender, settings=s, conv_id=conv_id, _state=state, **inp)
            except OrchestratorError as exc:
                tool_results.append(_tool_result(tu.id, {"error": str(exc)}, is_error=True))
                continue
            except Exception as exc:  # noqa: BLE001
                log.warning("tool_failed", tool=name, err=str(exc), conv_id=conv_id)
                tool_results.append(_tool_result(tu.id, {"error": str(exc)}, is_error=True))
                continue

            tool_results.append(_tool_result(tu.id, result))

            if name == "search_medicine" and isinstance(result, list):
                state["last_medicine_skus"] = [r.get("sku") for r in result if r.get("sku")]
            if name == "speak_to_mom" and isinstance(result, dict) and result.get("waiting_for_user"):
                wait_for_user = True
                state["last_speak_to_mom"] = inp

        messages.append({"role": "user", "content": tool_results})

        if wait_for_user:
            await _persist_pending(s, conv_id, state, messages)
            log.info("orchestrator_waiting_for_user", conv_id=conv_id, turns=turn + 1)
            return {"status": "awaiting_user", "turns": turn + 1}

    log.warning("orchestrator_max_turns", conv_id=conv_id, max_turns=s.LLM_MAX_TURNS)
    await _persist_done(s, conv_id, state, status="max_turns")
    return {"status": "max_turns_hit"}


async def resume_after_button(
    *,
    sender: str,
    conv_id: str,
    button_id: str,
    button_title: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Resume a paused agent loop after Mom taps a button.

    The button title is what the LLM asked for ("हाँ"/"नहीं"). The id is the
    interactive payload id we set when sending. We thread the title back as a
    user message and re-run the loop.
    """
    s = settings or get_settings()
    sess = await dynamo.get_session_state("mom", conv_id)
    if sess is None:
        log.warning("resume_no_session", conv_id=conv_id)
        return {"status": "no_session"}

    messages = sess.get("messages", [])
    intent = sess.get("intent", {"intent": "unknown"})
    state = sess.get("state", {})
    state["sender"] = sender
    state["conv_id"] = conv_id

    # Append Mom's button choice as a user turn.
    messages.append({"role": "user", "content": f"[button:{button_id}] {button_title}"})

    # Re-derive system prompt from intent (cheaper than re-storing it).
    profile = state.get("profile") or await dynamo.get_profile("mom")
    medicines = await dynamo.list_medicines("mom") if intent["intent"] == "medicine" else []
    usual_basket = (
        (await dynamo.get_usual_basket("mom")).get("items", [])
        if intent["intent"] == "grocery" else []
    )
    system = _system_for(intent["intent"], profile, medicines, usual_basket)

    client = _client(s)
    model = s.BEDROCK_MODEL_SONNET if s.USE_BEDROCK else "claude-sonnet-4-6"
    tools = T.tools_for(intent["intent"])

    for turn in range(s.LLM_MAX_TURNS):
        try:
            resp = await client.messages.create(
                model=model, max_tokens=2048, system=system, tools=tools, messages=messages,  # type: ignore[arg-type]
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("resume_llm_failed", err=str(exc), conv_id=conv_id)
            return {"status": "failed"}

        assistant_blocks = [_block_to_dict(b) for b in resp.content]
        messages.append({"role": "assistant", "content": assistant_blocks})
        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        if not tool_uses:
            await _persist_done(s, conv_id, state, status="done")
            return {"status": "done", "turns": turn + 1}

        tool_results: list[dict[str, Any]] = []
        wait_for_user = False
        for tu in tool_uses:
            impl = TOOL_IMPL.get(tu.name)
            if impl is None:
                tool_results.append(_tool_result(tu.id, {"error": f"unknown tool {tu.name}"}, is_error=True))
                continue
            try:
                result = await impl(
                    sender=sender, settings=s, conv_id=conv_id,
                    _state=state, **(tu.input or {}),
                )
            except Exception as exc:  # noqa: BLE001
                tool_results.append(_tool_result(tu.id, {"error": str(exc)}, is_error=True))
                continue
            tool_results.append(_tool_result(tu.id, result))
            if (tu.name == "speak_to_mom" and isinstance(result, dict)
                    and result.get("waiting_for_user")):
                wait_for_user = True

        messages.append({"role": "user", "content": tool_results})
        if wait_for_user:
            await _persist_pending(s, conv_id, state, messages)
            return {"status": "awaiting_user", "turns": turn + 1}

    return {"status": "max_turns_hit"}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _block_to_dict(block: Any) -> dict[str, Any]:
    """Convert an Anthropic content block (text|tool_use) into a JSON-safe dict.

    SDK blocks are pydantic models; ``.model_dump()`` works.
    """
    try:
        return block.model_dump()
    except AttributeError:
        # Fallback for raw dicts or other shapes.
        if isinstance(block, dict):
            return block
        return {"type": getattr(block, "type", "text"), "text": str(block)}


def _tool_result(tool_use_id: str, content: Any, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps(content, ensure_ascii=False, default=str),
        "is_error": is_error,
    }


async def _is_aborted(settings: Settings, conv_id: str) -> bool:
    sess = await dynamo.get_session_state("mom", conv_id)
    return bool(sess and sess.get("aborted"))


async def _send_abort_ack(settings: Settings, sender: str) -> None:
    try:
        audio = await sarvam.synthesize("ठीक है मम्मी, रोक दिया।", settings=settings)
        media_id = await whatsapp.upload_media(audio, "audio/mpeg", settings=settings)
        await whatsapp.send_audio(sender, media_id, settings=settings)
    except Exception as exc:  # noqa: BLE001
        log.warning("abort_ack_failed", err=str(exc))


async def _persist_pending(
    settings: Settings, conv_id: str, state: dict[str, Any], messages: list[dict[str, Any]]
) -> None:
    await dynamo.upsert_session(
        "mom", conv_id,
        {
            "intent": state.get("intent", {}),
            "state": {k: v for k, v in state.items() if k not in {"sender", "conv_id"}},
            "messages": messages,
            "status": "awaiting_user",
        },
    )


async def _persist_done(
    settings: Settings, conv_id: str, state: dict[str, Any], *, status: str
) -> None:
    try:
        await dynamo.upsert_session(
            "mom", conv_id,
            {"intent": state.get("intent", {}), "status": status, "closed_at": int(time.time() * 1000)},
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("persist_done_failed", err=str(exc), conv_id=conv_id)


# Make this importable without triggering the full import graph during tests.
__all__ = ["run_turn", "resume_after_button", "TOOL_IMPL", "AbortedByUser", "OrchestratorError",
           "_block_to_dict", "_tool_result"]


# Eagerly used by tests and integrators.
_ = asyncio  # silence unused import on type-only paths
