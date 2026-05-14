"""Sarvam Saaras v3 STT + Bulbul v3 TTS.

Built against `sarvamai==0.1.28`. The `AsyncSarvamAI` client is what we use;
the brief's "4.x" pin doesn't exist. See docs/DECISIONS.md for the deviation.

Audio shape contract:
- Inbound: WhatsApp voice notes are OGG/Opus, mono, 16 kHz. Pass them to STT
  as-is, ``input_audio_codec="ogg"``. No transcoding.
- Outbound: TTS returns base64 MP3 chunks via ``response.audios``; we
  base64-decode and concatenate to bytes. Meta accepts ``audio/mpeg``.
"""
from __future__ import annotations

import base64
from typing import Literal

from sarvamai import AsyncSarvamAI

from saathi.config import Settings, get_settings
from saathi.utils.hindi import apply_pronunciation_overrides
from saathi.utils.logging import get_logger

log = get_logger(__name__)

SttMode = Literal["transcribe", "codemix", "translit"]

# Bulbul v3 voices we expose. Brief mentioned `meera/arvind/amol` which the SDK
# does not have; if Mom prefers a different voice, pick from this allowed list.
ALLOWED_VOICES = {
    "vidya", "anushka", "manisha", "arya", "karun", "hitesh",
    "aditya", "ritu", "priya", "neha",
}

_client: AsyncSarvamAI | None = None


class SarvamError(RuntimeError):
    """Raised when Sarvam returns an error or unexpected payload."""


def _get_client(settings: Settings | None = None) -> AsyncSarvamAI:
    global _client
    if _client is None:
        s = settings or get_settings()
        _client = AsyncSarvamAI(api_subscription_key=s.SARVAM_API_KEY, timeout=15.0)
    return _client


async def transcribe(
    audio: bytes,
    *,
    mode: SttMode = "codemix",
    language_code: str = "hi-IN",
    settings: Settings | None = None,
) -> str:
    """Saaras v3 STT.

    `mode='codemix'` keeps English brand tokens as English (e.g. "Telma" stays
    "Telma" rather than "टेल्मा"). Use `mode='transcribe'` for pure Devanagari.
    For files >30s, switch to the Saaras batch API — not supported here.
    """
    client = _get_client(settings)
    try:
        resp = await client.speech_to_text.transcribe(
            file=("voice.oga", audio, "audio/ogg"),
            model="saaras:v3",
            mode=mode,
            language_code=language_code,
            input_audio_codec="ogg",
        )
    except Exception as exc:  # noqa: BLE001 — SDK surfaces several distinct types
        log.warning("sarvam_stt_failed", err=str(exc))
        raise SarvamError(f"stt failed: {exc}") from exc
    transcript = (resp.transcript or "").strip()
    log.info("sarvam_stt_ok", chars=len(transcript), mode=mode)
    return transcript


async def synthesize(
    text: str,
    *,
    voice: str | None = None,
    pitch: float = 0.0,
    pace: float = 1.0,
    loudness: float = 1.2,
    settings: Settings | None = None,
) -> bytes:
    """Bulbul v3 TTS.

    Applies brand pronunciation overrides automatically before sending. Returns
    raw MP3 bytes ready to upload to WhatsApp media as ``audio/mpeg``.
    """
    s = settings or get_settings()
    speaker = voice or s.TTS_VOICE
    if speaker not in ALLOWED_VOICES:
        raise SarvamError(f"voice {speaker!r} not in {sorted(ALLOWED_VOICES)}")

    text = apply_pronunciation_overrides(text)
    client = _get_client(s)
    try:
        resp = await client.text_to_speech.convert(
            text=text,
            target_language_code="hi-IN",
            speaker=speaker,
            model="bulbul:v3",
            output_audio_codec="mp3",
            pitch=pitch,
            pace=pace,
            loudness=loudness,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("sarvam_tts_failed", err=str(exc))
        raise SarvamError(f"tts failed: {exc}") from exc

    if not resp.audios:
        raise SarvamError("tts returned no audio")
    audio = b"".join(base64.b64decode(chunk) for chunk in resp.audios)
    log.info("sarvam_tts_ok", chars=len(text), bytes=len(audio), voice=speaker)
    return audio
