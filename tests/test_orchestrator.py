"""Orchestrator tests — fully mocked Anthropic + DDB + executors.

The orchestrator's contract is: drive the agent loop until either no more
tool_uses, or `speak_to_mom` returns with `waiting_for_user=True`.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from saathi.llm import orchestrator


def _block(type_: str, **kw):
    """Build a fake content block that quacks like an Anthropic SDK pydantic model."""
    obj = SimpleNamespace(type=type_, **kw)
    obj.model_dump = lambda: {"type": type_, **kw}
    return obj


def _resp(*blocks):
    return SimpleNamespace(content=list(blocks), stop_reason="end_turn")


@pytest.fixture
def fake_anthropic(monkeypatch):
    """Return a builder that you call with a list of responses Sonnet should
    return on successive turns."""
    def build(responses: list):
        client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=responses)))
        monkeypatch.setattr(orchestrator, "_client", lambda *_: client)
        return client
    return build


@pytest.fixture
def patched_dynamo(monkeypatch):
    """Stub dynamo so orchestrator doesn't hit AWS."""
    profile = {"name": "Mom", "address": {"pin": "302017"},
               "billers": {"electricity": {"consumer_number": "ABC123"}}}
    monkeypatch.setattr(orchestrator.dynamo, "get_profile", AsyncMock(return_value=profile))
    monkeypatch.setattr(orchestrator.dynamo, "list_medicines",
                        AsyncMock(return_value=[{"sku": "telma40", "brand": "Telma"}]))
    monkeypatch.setattr(orchestrator.dynamo, "get_usual_basket",
                        AsyncMock(return_value={"items": []}))
    monkeypatch.setattr(orchestrator.dynamo, "upsert_session", AsyncMock())
    monkeypatch.setattr(orchestrator.dynamo, "get_session_state", AsyncMock(return_value=None))
    return profile


@pytest.mark.asyncio
async def test_run_turn_no_tool_calls_completes(fake_anthropic, patched_dynamo):
    fake_anthropic([_resp(_block("text", text="ठीक है मम्मी"))])

    out = await orchestrator.run_turn(
        "नमस्ते", sender="9198X", conv_id="c1",
        intent={"intent": "medicine", "confidence": 0.9, "slots": {}},
    )
    assert out["status"] == "done"


@pytest.mark.asyncio
async def test_run_turn_search_then_speak_with_buttons_pauses(
    fake_anthropic, patched_dynamo, monkeypatch,
):
    # Sonnet turn 1: call search_medicine
    # Sonnet turn 2: call speak_to_mom with buttons
    fake_anthropic([
        _resp(_block("tool_use", id="t1", name="search_medicine", input={"query": "Telma 40"})),
        _resp(_block("tool_use", id="t2", name="speak_to_mom",
                     input={"text": "एक स्ट्रिप order करूं?", "buttons": ["हाँ", "नहीं"]})),
    ])

    # search_medicine impl returns one SKU
    fake_search = AsyncMock(return_value=[{"sku": "telma40", "brand": "Telma 40", "mrp": 150}])
    monkeypatch.setitem(orchestrator.TOOL_IMPL, "search_medicine",
                        lambda **kw: fake_search(query=kw["query"]))

    # speak_to_mom impl returns waiting_for_user
    fake_speak = AsyncMock(return_value={"voice_wamid": "wamid.v", "buttons_wamid": "wamid.b",
                                          "waiting_for_user": True})
    monkeypatch.setitem(orchestrator.TOOL_IMPL, "speak_to_mom",
                        lambda **kw: fake_speak(**{k: v for k, v in kw.items() if k in {"text", "buttons"}}))

    out = await orchestrator.run_turn(
        "टेलमा 40 खत्म हो गयी", sender="9198X", conv_id="c1",
        intent={"intent": "medicine", "confidence": 0.95, "slots": {"medicine_name": "Telma 40"}},
    )
    assert out["status"] == "awaiting_user"
    assert orchestrator.dynamo.upsert_session.await_count >= 1


@pytest.mark.asyncio
async def test_sku_guard_rejects_unknown_sku(fake_anthropic, patched_dynamo, monkeypatch):
    """Hard guard: place_medicine_order with sku not in last search results → tool_result is_error."""
    fake_anthropic([
        _resp(_block("tool_use", id="t1", name="search_medicine", input={"query": "Telma 40"})),
        _resp(_block("tool_use", id="t2", name="place_medicine_order",
                     input={"sku": "fake_sku_999", "quantity": 1, "prescription_s3_uri": "s3://x/y"})),
        _resp(_block("text", text="मम्मी, कुछ गड़बड़ है")),
    ])
    fake_search = AsyncMock(return_value=[{"sku": "telma40", "brand": "Telma"}])
    monkeypatch.setitem(orchestrator.TOOL_IMPL, "search_medicine",
                        lambda **kw: fake_search(query=kw["query"]))

    out = await orchestrator.run_turn(
        "टेलमा 40", sender="9198X", conv_id="c1",
        intent={"intent": "medicine", "confidence": 0.95, "slots": {}},
    )
    # Guard fires; orchestrator threads error tool_result; assistant ends turn cleanly.
    assert out["status"] == "done"


@pytest.mark.asyncio
async def test_aborted_session_short_circuits(fake_anthropic, patched_dynamo, monkeypatch):
    fake_anthropic([
        _resp(_block("tool_use", id="t1", name="search_medicine", input={"query": "Telma"})),
    ])
    monkeypatch.setattr(orchestrator.dynamo, "get_session_state",
                        AsyncMock(return_value={"aborted": True}))
    monkeypatch.setattr(orchestrator, "_send_abort_ack", AsyncMock())

    out = await orchestrator.run_turn(
        "टेलमा", sender="9198X", conv_id="c1",
        intent={"intent": "medicine", "confidence": 0.95, "slots": {}},
    )
    assert out["status"] == "aborted"


@pytest.mark.asyncio
async def test_max_turns_hit(fake_anthropic, patched_dynamo, monkeypatch):
    """If Sonnet keeps tool-calling forever, max_turns caps it."""
    fake_anthropic([
        _resp(_block("tool_use", id=f"t{i}", name="search_medicine", input={"query": "x"}))
        for i in range(10)
    ])
    monkeypatch.setitem(orchestrator.TOOL_IMPL, "search_medicine",
                        lambda **kw: AsyncMock(return_value=[])())

    out = await orchestrator.run_turn(
        "x", sender="9198X", conv_id="c1",
        intent={"intent": "medicine", "confidence": 0.95, "slots": {}},
    )
    assert out["status"] == "max_turns_hit"


def test_tool_result_serialization():
    out = orchestrator._tool_result("tu_x", {"order_id": "ORD123", "total": 240})
    assert out["type"] == "tool_result"
    assert out["tool_use_id"] == "tu_x"
    decoded = json.loads(out["content"])
    assert decoded["order_id"] == "ORD123"


def test_block_to_dict_pydantic_like():
    block = SimpleNamespace(type="text", text="hi")
    block.model_dump = lambda: {"type": "text", "text": "hi"}
    assert orchestrator._block_to_dict(block) == {"type": "text", "text": "hi"}


def test_block_to_dict_fallback():
    block = {"type": "text", "text": "hi"}
    assert orchestrator._block_to_dict(block) == block


def test_tool_impl_table_complete():
    """Every tool name in tools.SHARED + per-intent toolsets must have an impl."""
    from saathi.llm import tools as T
    all_names = {t["name"] for t in (T.MEDICINE_TOOLS + T.GROCERY_TOOLS + T.BILL_TOOLS)}
    missing = all_names - set(orchestrator.TOOL_IMPL.keys())
    assert not missing, f"tools without orchestrator dispatch: {missing}"
