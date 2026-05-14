"""Tests for the /telegram/webhook route — secret-token verify + chat_id allowlist."""
from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from saathi.app import app
from saathi.config import get_settings


def _callback(token: str, chat_id: int = 12345, action: str = "paid") -> dict[str, Any]:
    return {
        "update_id": 1,
        "callback_query": {
            "id": "cb1",
            "from": {"id": chat_id, "is_bot": False, "first_name": "Deep"},
            "message": {"message_id": 42, "chat": {"id": chat_id, "type": "private"}},
            "data": f"{action}:{token}",
        },
    }


def test_telegram_rejects_missing_secret():
    client = TestClient(app)
    r = client.post("/telegram/webhook", json=_callback("tk1"))
    assert r.status_code == 401


def test_telegram_rejects_wrong_secret():
    client = TestClient(app)
    r = client.post(
        "/telegram/webhook",
        json=_callback("tk1"),
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert r.status_code == 401


def test_telegram_drops_unauthorized_chat(monkeypatch):
    """Non-Deep chat_ids return 200 (don't 401 to Telegram), but no dispatch."""
    s = get_settings()
    called: list = []

    async def fake_handle(token, paid, settings=None, **_):
        called.append((token, paid))

    monkeypatch.setattr("saathi.app.concierge.handle_deep_confirmation", fake_handle)
    client = TestClient(app)
    r = client.post(
        "/telegram/webhook",
        json=_callback("tk1", chat_id=99999),  # not Deep's chat_id
        headers={"X-Telegram-Bot-Api-Secret-Token": s.TELEGRAM_WEBHOOK_SECRET},
    )
    assert r.status_code == 200
    assert called == []


def test_telegram_dispatches_paid(monkeypatch):
    s = get_settings()
    called: list = []

    async def fake_handle(token, paid, settings=None, **_):
        called.append((token, paid))

    monkeypatch.setattr("saathi.app.concierge.handle_deep_confirmation", fake_handle)
    client = TestClient(app)
    r = client.post(
        "/telegram/webhook",
        json=_callback("tk_pay", chat_id=int(s.TELEGRAM_DEEP_CHAT_ID), action="paid"),
        headers={"X-Telegram-Bot-Api-Secret-Token": s.TELEGRAM_WEBHOOK_SECRET},
    )
    assert r.status_code == 200
    assert called == [("tk_pay", True)]


def test_telegram_dispatches_skip(monkeypatch):
    s = get_settings()
    called: list = []

    async def fake_handle(token, paid, settings=None, **_):
        called.append((token, paid))

    monkeypatch.setattr("saathi.app.concierge.handle_deep_confirmation", fake_handle)
    client = TestClient(app)
    r = client.post(
        "/telegram/webhook",
        json=_callback("tk_skip", chat_id=int(s.TELEGRAM_DEEP_CHAT_ID), action="skip"),
        headers={"X-Telegram-Bot-Api-Secret-Token": s.TELEGRAM_WEBHOOK_SECRET},
    )
    assert r.status_code == 200
    assert called == [("tk_skip", False)]


def test_telegram_ignores_non_callback_updates():
    s = get_settings()
    client = TestClient(app)
    r = client.post(
        "/telegram/webhook",
        json={"update_id": 1, "message": {"text": "hi"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": s.TELEGRAM_WEBHOOK_SECRET},
    )
    assert r.status_code == 200
