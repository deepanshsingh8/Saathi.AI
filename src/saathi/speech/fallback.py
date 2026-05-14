"""Whisper STT fallback.

# STUB: replaced when first Sarvam 429 hits production (per docs/DAY_2.md).

Listed in docs/STATUS.md under "Stubs". Implementation goes here when needed —
likely a 30-line ``openai`` SDK wrapper around ``gpt-4o-transcribe``.
"""
from __future__ import annotations


async def transcribe_whisper_fallback(audio: bytes) -> str:
    raise NotImplementedError("Whisper fallback not yet wired (Day 2 stub)")
