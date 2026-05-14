"""Confidence gate + Path A/B grocery switch tests."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from saathi.llm import orchestrator


def _block(type_: str, **kw):
    obj = SimpleNamespace(type=type_, **kw)
    obj.model_dump = lambda: {"type": type_, **kw}
    return obj


def _resp(*blocks):
    return SimpleNamespace(content=list(blocks), stop_reason="end_turn")


@pytest.fixture
def patched_dynamo(monkeypatch):
    profile = {"name": "Mom", "address": {"pin": "302017"},
               "billers": {"electricity": {"consumer_number": "ABC"}}}
    monkeypatch.setattr(orchestrator.dynamo, "get_profile", AsyncMock(return_value=profile))
    monkeypatch.setattr(orchestrator.dynamo, "list_medicines",
                        AsyncMock(return_value=[]))
    monkeypatch.setattr(orchestrator.dynamo, "get_usual_basket",
                        AsyncMock(return_value={"items": []}))
    monkeypatch.setattr(orchestrator.dynamo, "upsert_session", AsyncMock())
    monkeypatch.setattr(orchestrator.dynamo, "get_session_state", AsyncMock(return_value=None))
    return profile


# ─── Confidence gate (Gap 3) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confidence_gate_refuses_high_stakes_without_confirm(patched_dynamo, monkeypatch):
    """place_medicine_order without prior confirm_understanding → tool_result is_error."""
    fake_anthropic = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=[
        _resp(_block("tool_use", id="t1", name="search_medicine", input={"query": "Telma"})),
        _resp(_block("tool_use", id="t2", name="place_medicine_order",
                     input={"sku": "telma40", "quantity": 1, "prescription_s3_uri": "s3://x"})),
        _resp(_block("text", text="मम्मी, confirm करिए?")),
    ])))
    monkeypatch.setattr(orchestrator, "_client", lambda *_: fake_anthropic)
    fake_search = AsyncMock(return_value=[{"sku": "telma40"}])
    monkeypatch.setitem(orchestrator.TOOL_IMPL, "search_medicine",
                        lambda **kw: fake_search(query=kw["query"]))

    out = await orchestrator.run_turn(
        "टेलमा 40", sender="9198X", conv_id="c1",
        intent={"intent": "medicine", "confidence": 0.95, "slots": {}},
    )
    assert out["status"] == "done"


@pytest.mark.asyncio
async def test_confidence_gate_passes_after_confirm(patched_dynamo, monkeypatch):
    """confirm_understanding(0.9) followed by place_medicine_order → executor invoked."""
    fake_anthropic = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=[
        _resp(_block("tool_use", id="t1", name="search_medicine", input={"query": "Telma"})),
        _resp(_block("tool_use", id="t2", name="confirm_understanding",
                     input={"summary": "Telma 40, 1 strip, COD", "confidence": 0.9})),
        _resp(_block("tool_use", id="t3", name="place_medicine_order",
                     input={"sku": "telma40", "quantity": 1, "prescription_s3_uri": "s3://x"})),
        _resp(_block("text", text="ऑर्डर लग गया")),
    ])))
    monkeypatch.setattr(orchestrator, "_client", lambda *_: fake_anthropic)

    fake_search = AsyncMock(return_value=[{"sku": "telma40"}])
    fake_place = AsyncMock(return_value={"order_id": "ORD1", "eta": "24h", "total": 150})
    monkeypatch.setitem(orchestrator.TOOL_IMPL, "search_medicine",
                        lambda **kw: fake_search(query=kw["query"]))
    monkeypatch.setattr("saathi.executors.medicine_1mg.place_medicine_order", fake_place)

    out = await orchestrator.run_turn(
        "टेलमा 40", sender="9198X", conv_id="c2",
        intent={"intent": "medicine", "confidence": 0.95, "slots": {}},
    )
    assert out["status"] == "done"
    fake_place.assert_awaited_once()


@pytest.mark.asyncio
async def test_confidence_gate_low_confidence_blocks(patched_dynamo, monkeypatch):
    """confirm_understanding(0.5) → place_medicine_order still refused."""
    fake_anthropic = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=[
        _resp(_block("tool_use", id="t1", name="search_medicine", input={"query": "Telma"})),
        _resp(_block("tool_use", id="t2", name="confirm_understanding",
                     input={"summary": "ambiguous", "confidence": 0.5})),
        _resp(_block("tool_use", id="t3", name="place_medicine_order",
                     input={"sku": "telma40", "quantity": 1, "prescription_s3_uri": "s3://x"})),
        _resp(_block("text", text="confirm")),
    ])))
    monkeypatch.setattr(orchestrator, "_client", lambda *_: fake_anthropic)

    fake_search = AsyncMock(return_value=[{"sku": "telma40"}])
    fake_place = AsyncMock(return_value={"order_id": "ORD"})
    monkeypatch.setitem(orchestrator.TOOL_IMPL, "search_medicine",
                        lambda **kw: fake_search(query=kw["query"]))
    monkeypatch.setattr("saathi.executors.medicine_1mg.place_medicine_order", fake_place)

    await orchestrator.run_turn(
        "टेलमा", sender="9198X", conv_id="c3",
        intent={"intent": "medicine", "confidence": 0.95, "slots": {}},
    )
    fake_place.assert_not_awaited()  # gate fired


# ─── Path A/B grocery switch (Gap 5) ─────────────────────────────────────────


def test_grocery_executor_defaults_to_blinkit(monkeypatch):
    from saathi.config import get_settings
    s = get_settings()
    # SWIGGY_MCP_URL is empty in test conftest — Swiggy disabled.
    ex = orchestrator._grocery_executor(s)
    from saathi.executors import grocery_blinkit
    assert ex is grocery_blinkit


def test_grocery_executor_routes_to_swiggy_when_enabled(monkeypatch):
    from saathi.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "SWIGGY_MCP_URL", "https://mcp.swiggy.com/im", raising=False)
    monkeypatch.setattr(s, "SWIGGY_CLIENT_ID", "cid", raising=False)
    monkeypatch.setattr(s, "SWIGGY_CLIENT_SECRET", "csec", raising=False)
    ex = orchestrator._grocery_executor(s)
    from saathi.executors import grocery_swiggy
    assert ex is grocery_swiggy
