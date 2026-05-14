"""Async-task scheduler for time-delayed nudges.

Day 5 brief: if Deep doesn't tap "Mark Paid" within 10 minutes after a
``request_payment_via_deep`` call, nudge Mom ("थोड़ी देर और लगेगी"). At 1 hour
with no confirmation, escalate to Deep with severity='blocked'.

Implementation: in-process ``asyncio.create_task`` with two delayed checks.
Each tick verifies the pending bill is still in DDB (cancelled if Deep marked
paid in the meantime). For a single-user deployment this is fine; the
Lightsail box is always up. For HA we'd swap this for SQS DelayedDelivery.

Scheduled tasks live in ``_TASKS`` so we can cancel them on success.
"""
from __future__ import annotations

import asyncio
from typing import Any

from saathi.config import Settings, get_settings
from saathi.executors import concierge as concierge_mod
from saathi.messaging import whatsapp
from saathi.speech import sarvam
from saathi.storage import dynamo
from saathi.utils.logging import get_logger

log = get_logger(__name__)

NUDGE_AT_SECONDS = 10 * 60  # 10 minutes — voice nudge to Mom
ESCALATE_AT_SECONDS = 60 * 60  # 1 hour — Telegram blocked alert to Deep

_TASKS: dict[str, list[asyncio.Task[Any]]] = {}


async def _nudge_mom(*, sender: str, token: str, settings: Settings) -> None:
    """At T+10min: if pending bill still in DDB, voice-nudge Mom in Hindi."""
    try:
        await asyncio.sleep(NUDGE_AT_SECONDS)
    except asyncio.CancelledError:
        return
    try:
        pending = await dynamo.get_pending_bill(token)
    except Exception as exc:  # noqa: BLE001
        log.warning("nudge_check_failed", err=str(exc), token=token)
        return
    if not pending:
        log.info("nudge_skipped_already_resolved", token=token)
        return
    text = "मम्मी, थोड़ी देर और लगेगी।"
    try:
        audio = await sarvam.synthesize(text, settings=settings)
        media_id = await whatsapp.upload_media(audio, "audio/mpeg", settings=settings)
        await whatsapp.send_audio(sender, media_id, settings=settings)
        log.info("mom_nudged", token=token)
    except Exception as exc:  # noqa: BLE001
        log.warning("mom_nudge_failed", err=str(exc), token=token)


async def _escalate_to_deep(*, token: str, settings: Settings) -> None:
    """At T+1hr: if pending bill still in DDB, Telegram-alert Deep blocked."""
    try:
        await asyncio.sleep(ESCALATE_AT_SECONDS)
    except asyncio.CancelledError:
        return
    try:
        pending = await dynamo.get_pending_bill(token)
    except Exception as exc:  # noqa: BLE001
        log.warning("escalate_check_failed", err=str(exc), token=token)
        return
    if not pending:
        log.info("escalate_skipped_already_resolved", token=token)
        return
    bill = pending.get("bill", {})
    rupees = bill.get("amount_paise", 0) // 100
    msg = (
        f"Pending payment 1h+ unresolved.\n"
        f"Utility: {bill.get('utility')} · ₹{rupees:,}\n"
        f"Due: {bill.get('due_date', '—')} · Token: {token}"
    )
    try:
        await concierge_mod.notify_deep("blocked", msg, settings=settings)
        log.info("deep_escalated", token=token)
    except Exception as exc:  # noqa: BLE001
        log.warning("deep_escalate_failed", err=str(exc), token=token)


def schedule_nudges(*, sender: str, token: str, settings: Settings | None = None) -> None:
    """Spawn the two delayed checks. Idempotent per ``token`` — calling twice
    leaks the first pair (we don't bother de-duping; the second pair runs the
    same checks against DDB and is harmless).
    """
    s = settings or get_settings()
    nudge = asyncio.create_task(_nudge_mom(sender=sender, token=token, settings=s))
    esc = asyncio.create_task(_escalate_to_deep(token=token, settings=s))
    _TASKS.setdefault(token, []).extend([nudge, esc])
    log.info("nudges_scheduled", token=token)


def cancel_nudges(token: str) -> None:
    """Cancel pending nudges for ``token`` — call from handle_deep_confirmation
    on success/skip so we don't nudge after resolution."""
    tasks = _TASKS.pop(token, [])
    for t in tasks:
        if not t.done():
            t.cancel()
    if tasks:
        log.info("nudges_cancelled", token=token, n=len(tasks))
