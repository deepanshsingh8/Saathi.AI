"""Tests for executors/concierge.py — Telegram via respx."""
from __future__ import annotations

import httpx
import pytest
import respx

from saathi.config import get_settings
from saathi.executors import concierge


@pytest.mark.asyncio
async def test_notify_deep_posts_to_telegram():
    s = get_settings()
    url = f"https://api.telegram.org/bot{s.TELEGRAM_BOT_TOKEN}/sendMessage"
    with respx.mock(assert_all_called=True) as router:
        route = router.post(url).respond(200, json={"ok": True, "result": {"message_id": 777}})
        async with httpx.AsyncClient() as client:
            msg_id = await concierge.notify_deep("warning", "test", client=client)
    assert msg_id == 777
    body = route.calls[0].request.content.decode()
    assert "warning" in body
    assert s.TELEGRAM_DEEP_CHAT_ID in body


@pytest.mark.asyncio
async def test_notify_deep_misconfigured(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "TELEGRAM_BOT_TOKEN", "", raising=False)
    with pytest.raises(concierge.ConciergeError):
        await concierge.notify_deep("info", "x", settings=s)


@pytest.mark.asyncio
async def test_notify_deep_telegram_error_propagates():
    s = get_settings()
    url = f"https://api.telegram.org/bot{s.TELEGRAM_BOT_TOKEN}/sendMessage"
    with respx.mock() as router:
        router.post(url).respond(500, text="server error")
        async with httpx.AsyncClient() as client:
            with pytest.raises(concierge.ConciergeError):
                await concierge.notify_deep("info", "x", client=client)


@pytest.mark.asyncio
async def test_send_payment_request_to_deep_persists_pending(monkeypatch):
    s = get_settings()
    captured: dict = {}

    async def fake_put_pending(token, payload, user="mom"):
        captured["token"] = token
        captured["payload"] = payload
    from saathi import scheduler as sched_mod
    from saathi.storage import dynamo
    monkeypatch.setattr(dynamo, "put_pending_bill", fake_put_pending)
    # Don't kick off real 10min/1hr tasks during tests.
    monkeypatch.setattr(sched_mod, "schedule_nudges", lambda **_: None)

    url = f"https://api.telegram.org/bot{s.TELEGRAM_BOT_TOKEN}/sendMessage"
    with respx.mock() as router:
        router.post(url).respond(200, json={"ok": True, "result": {"message_id": 42}})
        async with httpx.AsyncClient() as client:
            msg_id = await concierge.send_payment_request_to_deep(
                bill={"utility": "electricity", "amount_paise": 324000,
                      "payment_url": "https://x", "due_date": "2026-05-25",
                      "consumer_number": "ABC"},
                confirmation_token="tk1",
                mom_callback="9198X",
                client=client,
            )
    assert msg_id == 42
    assert captured["token"] == "tk1"
    assert captured["payload"]["bill"]["amount_paise"] == 324000


@pytest.mark.asyncio
async def test_fetch_telegram_photo_url_resolves():
    s = get_settings()
    url = f"https://api.telegram.org/bot{s.TELEGRAM_BOT_TOKEN}/getFile"
    with respx.mock() as router:
        router.post(url).respond(200, json={
            "ok": True,
            "result": {"file_path": "photos/file_42.jpg"},
        })
        async with httpx.AsyncClient() as client:
            out = await concierge.fetch_telegram_photo_url(file_id="ABCxyz", client=client)
    assert out.endswith("/file_42.jpg")
    assert s.TELEGRAM_BOT_TOKEN in out


@pytest.mark.asyncio
async def test_handle_deep_confirmation_paid_forwards_receipt(monkeypatch):
    """When Deep marks paid AND attaches a receipt, Mom gets voice + image."""
    s = get_settings()
    sent: list[tuple[str, str]] = []

    async def fake_synthesize(text, **_):
        return b"\xff\xfb-mp3"

    async def fake_upload_media(data, mime, **_):
        return "media_voice_1"

    async def fake_send_audio(to, media_id, **_):
        sent.append(("audio", media_id))
        return "wamid.audio"

    async def fake_send_image(to, *, link=None, media_id=None, caption=None, **_):
        sent.append(("image", link or media_id or ""))
        return "wamid.img"

    async def fake_get_pending(token, user="mom"):
        return {"bill": {"utility": "electricity", "amount_paise": 32400}, "mom_callback": "9198X"}

    async def fake_delete_pending(token, user="mom"):
        return None

    async def fake_fetch_photo(file_id, **_):
        return "https://api.telegram.org/file/bot.../photos/x.jpg"

    from saathi.storage import dynamo
    # concierge lazily imports these — patch the source modules.
    monkeypatch.setattr("saathi.speech.sarvam.synthesize", fake_synthesize)
    monkeypatch.setattr("saathi.messaging.whatsapp.upload_media", fake_upload_media)
    monkeypatch.setattr("saathi.messaging.whatsapp.send_audio", fake_send_audio)
    monkeypatch.setattr("saathi.messaging.whatsapp.send_image", fake_send_image)
    monkeypatch.setattr("saathi.executors.concierge.fetch_telegram_photo_url", fake_fetch_photo)
    monkeypatch.setattr(dynamo, "get_pending_bill", fake_get_pending)
    monkeypatch.setattr(dynamo, "delete_pending_bill", fake_delete_pending)
    from saathi import scheduler as sched_mod
    monkeypatch.setattr(sched_mod, "cancel_nudges", lambda _: None)

    out = await concierge.handle_deep_confirmation(
        token="tk1", paid=True, receipt_image_id="photo_xyz", settings=s,
    )
    assert out["status"] == "paid"
    kinds = [k for k, _ in sent]
    assert "audio" in kinds
    assert "image" in kinds


@pytest.mark.asyncio
async def test_handle_deep_confirmation_no_pending_returns_no_pending(monkeypatch):
    from saathi.storage import dynamo
    monkeypatch.setattr(dynamo, "get_pending_bill", lambda token, user="mom": _none())
    out = await concierge.handle_deep_confirmation(token="tk_missing", paid=True)
    assert out["status"] == "no_pending"


async def _none():
    return None
