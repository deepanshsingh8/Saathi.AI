"""Tests for the AI selector fallback (Day 6 polish 5)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from saathi.executors import fallback


def _fake_text_block(text: str):
    return SimpleNamespace(type="text", text=text)


@pytest.mark.asyncio
async def test_primary_succeeds_no_fallback(monkeypatch):
    """Happy path: primary returns, no LLM call needed."""
    page = MagicMock()
    primary = AsyncMock(return_value="ok")

    asked: list = []
    monkeypatch.setattr(fallback, "_ask_for_selector",
                        AsyncMock(side_effect=lambda *a, **k: asked.append(a) or "x"))

    out = await fallback.with_selector_fallback(
        page, primary=primary, intent="click X", original_selector="role=button[name='X']",
    )
    assert out == "ok"
    primary.assert_awaited_once()
    assert asked == []


@pytest.mark.asyncio
async def test_fallback_invokes_llm_and_clicks(monkeypatch):
    page = MagicMock()
    page.content = AsyncMock(return_value="<html><button id='x'>X</button></html>")
    page.locator.return_value.first.click = AsyncMock(return_value=None)

    primary = AsyncMock(side_effect=PlaywrightTimeoutError("boom"))
    ask = AsyncMock(return_value="#x")
    monkeypatch.setattr(fallback, "_ask_for_selector", ask)

    out = await fallback.with_selector_fallback(
        page, primary=primary, intent="click the X button", original_selector="role=button[name='X']",
    )
    assert out is None  # fallback returns None on success
    ask.assert_awaited_once()
    page.locator.assert_called_with("#x")


@pytest.mark.asyncio
async def test_fallback_no_match_propagates(monkeypatch):
    page = MagicMock()
    page.content = AsyncMock(return_value="<html></html>")
    primary = AsyncMock(side_effect=PlaywrightTimeoutError("boom"))
    monkeypatch.setattr(fallback, "_ask_for_selector", AsyncMock(return_value="NO_MATCH"))

    with pytest.raises(PlaywrightTimeoutError):
        await fallback.with_selector_fallback(
            page, primary=primary, intent="click X", original_selector="x",
        )


@pytest.mark.asyncio
async def test_fallback_second_click_failure_propagates(monkeypatch):
    page = MagicMock()
    page.content = AsyncMock(return_value="<html></html>")
    page.locator.return_value.first.click = AsyncMock(side_effect=RuntimeError("nope"))
    primary = AsyncMock(side_effect=PlaywrightTimeoutError("first"))
    monkeypatch.setattr(fallback, "_ask_for_selector", AsyncMock(return_value="#x"))

    with pytest.raises(PlaywrightTimeoutError):
        await fallback.with_selector_fallback(
            page, primary=primary, intent="x", original_selector="y",
        )


@pytest.mark.asyncio
async def test_ask_for_selector_strips_whitespace(monkeypatch):
    """The LLM may return a selector with surrounding whitespace; strip it."""
    fake_resp = SimpleNamespace(content=[_fake_text_block("  #x  \n")])
    fake_client = SimpleNamespace(messages=SimpleNamespace(
        create=AsyncMock(return_value=fake_resp),
    ))
    # Intercept Anthropic client construction.
    monkeypatch.setattr("saathi.executors.fallback.AsyncAnthropic",
                        lambda **_: fake_client)
    monkeypatch.setattr("saathi.executors.fallback.AsyncAnthropicBedrock",
                        lambda **_: fake_client)
    from saathi.config import get_settings
    s = get_settings()
    out = await fallback._ask_for_selector(s, "click x", "y", "<html></html>")
    assert out == "#x"


@pytest.mark.asyncio
async def test_ask_for_selector_llm_failure_returns_no_match(monkeypatch):
    fake_client = SimpleNamespace(messages=SimpleNamespace(
        create=AsyncMock(side_effect=RuntimeError("network")),
    ))
    monkeypatch.setattr("saathi.executors.fallback.AsyncAnthropic",
                        lambda **_: fake_client)
    monkeypatch.setattr("saathi.executors.fallback.AsyncAnthropicBedrock",
                        lambda **_: fake_client)
    from saathi.config import get_settings
    out = await fallback._ask_for_selector(get_settings(), "x", "y", "<html></html>")
    assert out == "NO_MATCH"
