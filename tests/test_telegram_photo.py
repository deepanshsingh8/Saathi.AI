"""Tests for inbound Telegram photo (receipt forwarding) on /telegram/webhook."""
from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from saathi.app import _extract_token_from_reply, app
from saathi.config import get_settings


def _photo_update(token_in_reply_text: str, chat_id: int) -> dict[str, Any]:
    return {
        "update_id": 7,
        "message": {
            "message_id": 99,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id},
            "photo": [
                {"file_id": "small_id", "width": 90, "height": 90},
                {"file_id": "big_id", "width": 800, "height": 800},
            ],
            "reply_to_message": {
                "message_id": 42,
                "text": (
                    "💸 Saathi bill payment\nUtility: electricity\nAmount: ₹3,240\n"
                    f"Token: {token_in_reply_text}\n\nOpen payment page"
                ),
            },
        },
    }


def test_extract_token_from_reply_pulls_hex():
    text = "Token: 0123456789abcdef0123456789abcdef\nrest"
    msg = {"text": text}
    assert _extract_token_from_reply(msg) == "0123456789abcdef0123456789abcdef"


def test_extract_token_from_reply_no_match():
    assert _extract_token_from_reply({"text": "no hex here"}) is None
    assert _extract_token_from_reply({}) is None


def test_telegram_photo_dispatches_paid_with_receipt(monkeypatch):
    s = get_settings()
    captured: list[dict] = []

    async def fake_handle(token, paid, settings=None, receipt_image_id=None, **_):
        captured.append({"token": token, "paid": paid, "receipt": receipt_image_id})

    monkeypatch.setattr("saathi.app.concierge.handle_deep_confirmation", fake_handle)
    client = TestClient(app)
    payload = _photo_update(
        token_in_reply_text="0123456789abcdef0123456789abcdef",
        chat_id=int(s.TELEGRAM_DEEP_CHAT_ID),
    )
    r = client.post(
        "/telegram/webhook", json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": s.TELEGRAM_WEBHOOK_SECRET},
    )
    assert r.status_code == 200
    assert len(captured) == 1
    assert captured[0]["paid"] is True
    assert captured[0]["receipt"] == "big_id"  # largest variant
    assert captured[0]["token"] == "0123456789abcdef0123456789abcdef"


def test_telegram_photo_from_unauthorized_chat_dropped(monkeypatch):
    s = get_settings()
    captured: list = []
    monkeypatch.setattr(
        "saathi.app.concierge.handle_deep_confirmation",
        lambda **kw: captured.append(kw),
    )
    payload = _photo_update("0" * 32, chat_id=99999)
    client = TestClient(app)
    r = client.post(
        "/telegram/webhook", json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": s.TELEGRAM_WEBHOOK_SECRET},
    )
    assert r.status_code == 200
    assert captured == []


def test_telegram_photo_without_token_in_reply_dropped(monkeypatch):
    s = get_settings()
    captured: list = []
    monkeypatch.setattr(
        "saathi.app.concierge.handle_deep_confirmation",
        lambda **kw: captured.append(kw),
    )
    payload = _photo_update("not-a-token", chat_id=int(s.TELEGRAM_DEEP_CHAT_ID))
    client = TestClient(app)
    r = client.post(
        "/telegram/webhook", json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": s.TELEGRAM_WEBHOOK_SECRET},
    )
    assert r.status_code == 200
    assert captured == []
