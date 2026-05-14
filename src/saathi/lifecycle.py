"""FastAPI startup/shutdown lifecycle hooks.

Day 6 polish 7:
- **Sarvam keepalive**: ping the TTS endpoint every ~4 minutes so the first
  call of an idle period doesn't pay cold-start latency.
- **Browserbase pre-warm**: when an intent classifies as ``medicine`` or
  ``grocery`` we trigger a session-create off-thread so the Playwright
  connect lands quickly when the executor actually runs. Hooked from
  ``handle_voice_turn`` via ``maybe_prewarm_browserbase(intent)``.

Both are best-effort — failures are logged and never raise. The pre-warm
pool TTL is short (120s); stale sessions are quietly closed by Browserbase
on its side.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from saathi.config import Settings, get_settings
from saathi.utils.logging import get_logger

log = get_logger(__name__)

KEEPALIVE_EVERY_SECONDS = 4 * 60
PREWARM_TTL_SECONDS = 120

_keepalive_task: asyncio.Task[Any] | None = None
_prewarm: dict[str, Any] = {}  # {created_at, connect_url}
_prewarm_task: asyncio.Task[Any] | None = None


# ─── Sarvam keepalive ────────────────────────────────────────────────────────


async def _sarvam_keepalive_loop(settings: Settings) -> None:
    from saathi.speech import sarvam
    while True:
        try:
            await asyncio.sleep(KEEPALIVE_EVERY_SECONDS)
        except asyncio.CancelledError:
            log.info("sarvam_keepalive_cancelled")
            return
        try:
            # Cheapest possible call — 1-char synth, discarded.
            await sarvam.synthesize("ओके", settings=settings)
            log.info("sarvam_keepalive_ok")
        except Exception as exc:  # noqa: BLE001
            log.warning("sarvam_keepalive_failed", err=str(exc))


def start_sarvam_keepalive(settings: Settings | None = None) -> None:
    global _keepalive_task
    if _keepalive_task is not None and not _keepalive_task.done():
        return
    s = settings or get_settings()
    if not s.SARVAM_API_KEY:
        log.info("sarvam_keepalive_skipped_no_key")
        return
    _keepalive_task = asyncio.create_task(_sarvam_keepalive_loop(s))
    log.info("sarvam_keepalive_started")


def stop_sarvam_keepalive() -> None:
    global _keepalive_task
    if _keepalive_task and not _keepalive_task.done():
        _keepalive_task.cancel()
        _keepalive_task = None


# ─── Browserbase pre-warm ────────────────────────────────────────────────────


async def _create_browserbase_session(settings: Settings) -> str:
    """Block on Browserbase session create. Returns the connect URL."""
    from browserbase import Browserbase
    bb = Browserbase(api_key=settings.BROWSERBASE_API_KEY)
    sess = bb.sessions.create(project_id=settings.BROWSERBASE_PROJECT_ID)
    return sess.connect_url


def maybe_prewarm_browserbase(intent: str, *, settings: Settings | None = None) -> None:
    """Fire-and-forget pre-warm for executor-bound intents.

    Idempotent within ``PREWARM_TTL_SECONDS`` — repeated calls inside the TTL
    don't kick off a second session.
    """
    global _prewarm_task
    if intent not in {"medicine", "grocery"}:
        return
    s = settings or get_settings()
    if not s.BROWSERBASE_API_KEY:
        return
    now = time.time()
    if _prewarm and now - _prewarm.get("created_at", 0) < PREWARM_TTL_SECONDS:
        return  # warm session still valid
    if _prewarm_task and not _prewarm_task.done():
        return  # in flight

    async def _warm() -> None:
        try:
            url = await _create_browserbase_session(s)
            _prewarm.update({"created_at": time.time(), "connect_url": url})
            log.info("browserbase_prewarmed", ttl=PREWARM_TTL_SECONDS)
        except Exception as exc:  # noqa: BLE001
            log.warning("browserbase_prewarm_failed", err=str(exc))

    _prewarm_task = asyncio.create_task(_warm())


def get_prewarmed_connect_url() -> str | None:
    """Executors call this to consume a warm session URL if available.

    Returns None if no session is warm or the warm session has expired.
    Single-use: returning the URL clears it (next prewarm will be needed).
    """
    if not _prewarm:
        return None
    age = time.time() - _prewarm.get("created_at", 0)
    if age > PREWARM_TTL_SECONDS:
        _prewarm.clear()
        return None
    url = _prewarm.pop("connect_url", None)
    _prewarm.clear()
    return url
