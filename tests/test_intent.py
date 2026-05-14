"""Intent classifier tests — mocked AsyncAnthropic.messages.create."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from saathi.llm import intent as intent_mod


def _fake_response(text: str) -> SimpleNamespace:
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block])


@pytest.mark.asyncio
async def test_classify_medicine(monkeypatch):
    intent_mod._client.cache_clear()
    payload = (
        '{"intent":"medicine","confidence":0.95,'
        '"slots":{"medicine_name":"Telma 40","quantity_hint":null}}'
    )
    fake_client = SimpleNamespace(messages=SimpleNamespace(
        create=AsyncMock(return_value=_fake_response(payload))
    ))
    monkeypatch.setattr(intent_mod, "_client", lambda *_: fake_client)

    out = await intent_mod.classify("टेलमा 40 खत्म हो गयी")
    assert out["intent"] == "medicine"
    assert out["confidence"] >= 0.9
    assert out["slots"]["medicine_name"] == "Telma 40"


@pytest.mark.asyncio
async def test_classify_chitchat(monkeypatch):
    fake_client = SimpleNamespace(messages=SimpleNamespace(
        create=AsyncMock(return_value=_fake_response(
            '{"intent":"chitchat","confidence":0.99,"slots":{}}'
        ))
    ))
    monkeypatch.setattr(intent_mod, "_client", lambda *_: fake_client)
    out = await intent_mod.classify("कैसी हो?")
    assert out["intent"] == "chitchat"


@pytest.mark.asyncio
async def test_classify_handles_codefence(monkeypatch):
    raw = '```json\n{"intent":"grocery","confidence":0.92,"slots":{"items":["दूध"]}}\n```'
    fake_client = SimpleNamespace(messages=SimpleNamespace(
        create=AsyncMock(return_value=_fake_response(raw))
    ))
    monkeypatch.setattr(intent_mod, "_client", lambda *_: fake_client)
    out = await intent_mod.classify("दूध मंगा दो")
    assert out["intent"] == "grocery"


@pytest.mark.asyncio
async def test_classify_invalid_intent_falls_back_to_unknown(monkeypatch):
    fake_client = SimpleNamespace(messages=SimpleNamespace(
        create=AsyncMock(return_value=_fake_response(
            '{"intent":"weather","confidence":0.5,"slots":{}}'
        ))
    ))
    monkeypatch.setattr(intent_mod, "_client", lambda *_: fake_client)
    out = await intent_mod.classify("मौसम कैसा है")
    assert out["intent"] == "unknown"


@pytest.mark.asyncio
async def test_classify_garbage_falls_back(monkeypatch):
    fake_client = SimpleNamespace(messages=SimpleNamespace(
        create=AsyncMock(return_value=_fake_response("not json at all"))
    ))
    monkeypatch.setattr(intent_mod, "_client", lambda *_: fake_client)
    out = await intent_mod.classify("xyz")
    assert out == intent_mod.UNKNOWN


@pytest.mark.asyncio
async def test_classify_call_failure_returns_unknown(monkeypatch):
    fake_client = SimpleNamespace(messages=SimpleNamespace(
        create=AsyncMock(side_effect=RuntimeError("network down"))
    ))
    monkeypatch.setattr(intent_mod, "_client", lambda *_: fake_client)
    out = await intent_mod.classify("anything")
    assert out == intent_mod.UNKNOWN
