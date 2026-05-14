"""Lifecycle (Sarvam keepalive + Browserbase pre-warm) tests."""
from __future__ import annotations

import asyncio

import pytest

from saathi import lifecycle


@pytest.mark.asyncio
async def test_keepalive_skipped_with_no_key(monkeypatch):
    from saathi.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "SARVAM_API_KEY", "", raising=False)
    lifecycle.start_sarvam_keepalive(s)
    assert lifecycle._keepalive_task is None
    lifecycle.stop_sarvam_keepalive()


@pytest.mark.asyncio
async def test_keepalive_starts_and_stops(monkeypatch):
    """Start the keepalive, then stop — task should cancel cleanly."""
    monkeypatch.setattr(lifecycle, "KEEPALIVE_EVERY_SECONDS", 0.05)

    async def fake_synth(*a, **k):
        return b""

    monkeypatch.setattr("saathi.speech.sarvam.synthesize", fake_synth)
    lifecycle.start_sarvam_keepalive()
    assert lifecycle._keepalive_task is not None
    await asyncio.sleep(0.15)  # let it tick a couple times
    lifecycle.stop_sarvam_keepalive()
    await asyncio.sleep(0.05)
    assert lifecycle._keepalive_task is None or lifecycle._keepalive_task.done()


def test_prewarm_skipped_for_non_executor_intents():
    lifecycle._prewarm.clear()
    lifecycle.maybe_prewarm_browserbase("chitchat")
    assert lifecycle._prewarm == {}


def test_prewarm_skipped_without_api_key(monkeypatch):
    from saathi.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "BROWSERBASE_API_KEY", "", raising=False)
    lifecycle._prewarm.clear()
    lifecycle.maybe_prewarm_browserbase("medicine", settings=s)
    assert lifecycle._prewarm == {}


def test_get_prewarmed_returns_none_when_empty():
    lifecycle._prewarm.clear()
    assert lifecycle.get_prewarmed_connect_url() is None


def test_get_prewarmed_returns_then_clears():
    import time
    lifecycle._prewarm.clear()
    lifecycle._prewarm.update({"created_at": time.time(), "connect_url": "wss://x"})
    assert lifecycle.get_prewarmed_connect_url() == "wss://x"
    # Single-use: subsequent call returns None.
    assert lifecycle.get_prewarmed_connect_url() is None


def test_get_prewarmed_returns_none_when_expired():
    import time
    lifecycle._prewarm.clear()
    lifecycle._prewarm.update({"created_at": time.time() - 9999, "connect_url": "wss://stale"})
    assert lifecycle.get_prewarmed_connect_url() is None
    assert lifecycle._prewarm == {}
