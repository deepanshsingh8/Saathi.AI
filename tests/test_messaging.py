"""Day 1 messaging tests: signature verify, webhook routing, send_text."""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from saathi.app import GREETING_HI, app, handle_text_message
from saathi.config import get_settings
from saathi.messaging import webhooks, whatsapp

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _make_text_payload(sender: str, text: str = "hello") -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "..."},
                            "messages": [
                                {
                                    "from": sender,
                                    "id": "wamid.in",
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def _make_status_payload() -> dict[str, Any]:
    """Cloud API also POSTs delivery/read status updates with no `messages` key."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "statuses": [
                                {"id": "wamid.out", "status": "delivered", "timestamp": "1"}
                            ],
                        },
                    }
                ],
            }
        ],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Signature verification
# ──────────────────────────────────────────────────────────────────────────────


def test_signature_match():
    body = b'{"hello":"world"}'
    sig = _sign(body, "test-app-secret")
    assert webhooks.verify_signature(body, sig, "test-app-secret") is True


def test_signature_mismatch_wrong_secret():
    body = b'{"hello":"world"}'
    sig = _sign(body, "wrong-secret")
    assert webhooks.verify_signature(body, sig, "test-app-secret") is False


def test_signature_missing_header():
    assert webhooks.verify_signature(b"x", None, "test-app-secret") is False


def test_signature_malformed_header():
    assert webhooks.verify_signature(b"x", "md5=abc", "test-app-secret") is False


# ──────────────────────────────────────────────────────────────────────────────
# Webhook routing
# ──────────────────────────────────────────────────────────────────────────────


def test_webhook_verify_handshake_ok():
    s = get_settings()
    client = TestClient(app)
    r = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": s.WA_VERIFY_TOKEN,
            "hub.challenge": "424242",
        },
    )
    assert r.status_code == 200
    assert r.text == "424242"


def test_webhook_verify_handshake_bad_token():
    client = TestClient(app)
    r = client.get(
        "/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"},
    )
    assert r.status_code == 403


def test_healthz():
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "service": "saathi"}


def test_webhook_inbound_from_mom_dispatches(monkeypatch):
    s = get_settings()
    called: list[dict[str, Any]] = []

    async def fake_handler(msg, *, settings=None):
        called.append(msg)

    monkeypatch.setattr("saathi.app.handle_text_message", fake_handler)

    payload = _make_text_payload(sender=s.WA_MOM_NUMBER.lstrip("+"))
    body = json.dumps(payload).encode()
    sig = _sign(body, s.WA_APP_SECRET)

    client = TestClient(app)
    r = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": sig})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert len(called) == 1
    assert called[0]["from"] == s.WA_MOM_NUMBER.lstrip("+")


def test_webhook_inbound_from_other_silently_dropped(monkeypatch):
    s = get_settings()
    called: list[Any] = []

    async def fake_handler(msg, *, settings=None):
        called.append(msg)

    monkeypatch.setattr("saathi.app.handle_text_message", fake_handler)

    payload = _make_text_payload(sender="9199999999999")
    body = json.dumps(payload).encode()
    sig = _sign(body, s.WA_APP_SECRET)

    client = TestClient(app)
    r = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": sig})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert called == []


def test_webhook_inbound_status_update_ignored(monkeypatch):
    s = get_settings()
    called: list[Any] = []

    async def fake_handler(msg, *, settings=None):
        called.append(msg)

    monkeypatch.setattr("saathi.app.handle_text_message", fake_handler)

    body = json.dumps(_make_status_payload()).encode()
    sig = _sign(body, s.WA_APP_SECRET)

    client = TestClient(app)
    r = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": sig})
    assert r.status_code == 200
    assert called == []


def test_webhook_inbound_bad_signature_rejected():
    payload = _make_text_payload(sender="9199999999999")
    body = json.dumps(payload).encode()
    client = TestClient(app)
    r = client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=deadbeef"},
    )
    assert r.status_code == 401


# ──────────────────────────────────────────────────────────────────────────────
# send_text via respx
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_text_ok():
    s = get_settings()
    url = f"https://graph.facebook.com/v22.0/{s.WA_PHONE_ID}/messages"

    with respx.mock(assert_all_called=True) as router:
        route = router.post(url).respond(
            200,
            json={
                "messaging_product": "whatsapp",
                "contacts": [{"input": s.WA_MOM_NUMBER, "wa_id": "..."}],
                "messages": [{"id": "wamid.test123"}],
            },
        )
        async with httpx.AsyncClient() as client:
            wamid = await whatsapp.send_text(s.WA_MOM_NUMBER, "hi", client=client)

    assert wamid == "wamid.test123"
    sent = route.calls[0].request
    assert sent.headers["authorization"] == f"Bearer {s.WA_ACCESS_TOKEN}"
    body = json.loads(sent.content)
    assert body["messaging_product"] == "whatsapp"
    assert body["to"] == s.WA_MOM_NUMBER
    assert body["type"] == "text"
    assert body["text"]["body"] == "hi"


@pytest.mark.asyncio
async def test_send_text_raises_on_400():
    s = get_settings()
    url = f"https://graph.facebook.com/v22.0/{s.WA_PHONE_ID}/messages"

    with respx.mock() as router:
        router.post(url).respond(400, json={"error": {"message": "bad recipient"}})
        async with httpx.AsyncClient() as client:
            with pytest.raises(whatsapp.WhatsAppError) as exc:
                await whatsapp.send_text("+910000000000", "hi", client=client)

    assert exc.value.status == 400


@pytest.mark.asyncio
async def test_handle_text_message_sends_greeting():
    s = get_settings()
    sent_args: dict[str, Any] = {}

    async def fake_send(to, body, *, settings=None, client=None):
        sent_args["to"] = to
        sent_args["body"] = body
        return "wamid.fake"

    # Monkeypatch the symbol the handler imports.
    import saathi.app as app_mod

    original = app_mod.whatsapp.send_text
    app_mod.whatsapp.send_text = fake_send  # type: ignore[assignment]
    try:
        msg = {"from": s.WA_MOM_NUMBER.lstrip("+"), "type": "text", "text": {"body": "hello"}}
        await handle_text_message(msg)
    finally:
        app_mod.whatsapp.send_text = original  # type: ignore[assignment]

    assert sent_args["to"] == s.WA_MOM_NUMBER.lstrip("+")
    assert sent_args["body"] == GREETING_HI
