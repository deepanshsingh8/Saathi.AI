"""Scheduler tests — fast tickless versions of the 10min/1hr nudges."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from saathi import scheduler


@pytest.mark.asyncio
async def test_schedule_then_cancel_clears_tasks(monkeypatch):
    """Schedule both nudges, then cancel — both tasks should be done/cancelled."""
    monkeypatch.setattr(scheduler, "NUDGE_AT_SECONDS", 100)
    monkeypatch.setattr(scheduler, "ESCALATE_AT_SECONDS", 100)

    scheduler.schedule_nudges(sender="9198X", token="tkA")
    assert "tkA" in scheduler._TASKS
    assert len(scheduler._TASKS["tkA"]) == 2
    scheduler.cancel_nudges("tkA")
    assert "tkA" not in scheduler._TASKS


@pytest.mark.asyncio
async def test_nudge_skipped_if_pending_already_resolved(monkeypatch):
    """If pending bill is gone by the time the nudge fires, no voice is sent."""
    monkeypatch.setattr(scheduler, "NUDGE_AT_SECONDS", 0)  # fire immediately
    sent_voice: list = []

    async def fake_get_pending(token, user="mom"):
        return None  # already resolved

    async def fake_synthesize(*a, **k):
        sent_voice.append("synth")
        return b""

    monkeypatch.setattr("saathi.scheduler.dynamo.get_pending_bill", fake_get_pending)
    monkeypatch.setattr("saathi.scheduler.sarvam.synthesize", fake_synthesize)

    await scheduler._nudge_mom(sender="9198X", token="tkB", settings=None)  # type: ignore[arg-type]
    assert sent_voice == []


@pytest.mark.asyncio
async def test_nudge_sends_voice_if_still_pending(monkeypatch):
    monkeypatch.setattr(scheduler, "NUDGE_AT_SECONDS", 0)
    sent: list = []

    async def fake_get_pending(token, user="mom"):
        return {"bill": {"utility": "electricity", "amount_paise": 100}}

    async def fake_synthesize(text, **_):
        sent.append(("synth", text))
        return b"\xff\xfb"

    async def fake_upload(data, mime, **_):
        return "mid"

    async def fake_send_audio(to, mid, **_):
        sent.append(("send", to))
        return "wamid"

    monkeypatch.setattr("saathi.scheduler.dynamo.get_pending_bill", fake_get_pending)
    monkeypatch.setattr("saathi.scheduler.sarvam.synthesize", fake_synthesize)
    monkeypatch.setattr("saathi.scheduler.whatsapp.upload_media", fake_upload)
    monkeypatch.setattr("saathi.scheduler.whatsapp.send_audio", fake_send_audio)
    from saathi.config import get_settings
    s = get_settings()

    await scheduler._nudge_mom(sender="9198X", token="tkC", settings=s)
    kinds = [k for k, _ in sent]
    assert "synth" in kinds
    assert "send" in kinds


@pytest.mark.asyncio
async def test_escalate_telegram_called_if_still_pending(monkeypatch):
    monkeypatch.setattr(scheduler, "ESCALATE_AT_SECONDS", 0)

    async def fake_get_pending(token, user="mom"):
        return {"bill": {"utility": "electricity", "amount_paise": 32400, "due_date": "x"}}

    notify = AsyncMock(return_value=99)
    monkeypatch.setattr("saathi.scheduler.dynamo.get_pending_bill", fake_get_pending)
    monkeypatch.setattr("saathi.scheduler.concierge_mod.notify_deep", notify)
    from saathi.config import get_settings

    await scheduler._escalate_to_deep(token="tkD", settings=get_settings())
    notify.assert_awaited_once()
    args = notify.await_args
    assert args.args[0] == "blocked"
    assert "tkD" in args.args[1]


@pytest.mark.asyncio
async def test_cancel_nudges_idempotent_for_unknown_token():
    scheduler.cancel_nudges("never_scheduled")  # should not raise
