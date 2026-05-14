"""Tests for speech/sarvam.py — mocked AsyncSarvamAI client.

Real-audio fixture tests (``mom_hello.oga`` etc.) require recordings from Mom
and a live Sarvam key. They live behind ``@pytest.mark.integration`` and are
gated on the ``SARVAM_INTEGRATION=1`` env var so CI never hits the network.
"""
from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from saathi.speech import sarvam


@pytest.mark.asyncio
async def test_transcribe_happy_path(monkeypatch):
    fake_resp = SimpleNamespace(transcript="नमस्ते मम्मी")
    fake_stt = MagicMock()
    fake_stt.transcribe = AsyncMock(return_value=fake_resp)
    fake_client = SimpleNamespace(speech_to_text=fake_stt, text_to_speech=MagicMock())

    monkeypatch.setattr(sarvam, "_client", fake_client)

    out = await sarvam.transcribe(b"\x00\x01\x02", mode="codemix")
    assert out == "नमस्ते मम्मी"

    call = fake_stt.transcribe.await_args
    assert call.kwargs["model"] == "saaras:v3"
    assert call.kwargs["mode"] == "codemix"
    assert call.kwargs["language_code"] == "hi-IN"
    assert call.kwargs["input_audio_codec"] == "ogg"


@pytest.mark.asyncio
async def test_transcribe_propagates_sarvam_error(monkeypatch):
    fake_stt = MagicMock()
    fake_stt.transcribe = AsyncMock(side_effect=RuntimeError("429"))
    fake_client = SimpleNamespace(speech_to_text=fake_stt, text_to_speech=MagicMock())

    monkeypatch.setattr(sarvam, "_client", fake_client)

    with pytest.raises(sarvam.SarvamError):
        await sarvam.transcribe(b"x")


@pytest.mark.asyncio
async def test_synthesize_decodes_base64_chunks(monkeypatch):
    chunk1 = base64.b64encode(b"\xff\xfb-mp3-part-1").decode()
    chunk2 = base64.b64encode(b"-part-2").decode()
    fake_resp = SimpleNamespace(audios=[chunk1, chunk2])
    fake_tts = MagicMock()
    fake_tts.convert = AsyncMock(return_value=fake_resp)
    fake_client = SimpleNamespace(speech_to_text=MagicMock(), text_to_speech=fake_tts)

    monkeypatch.setattr(sarvam, "_client", fake_client)

    out = await sarvam.synthesize("नमस्ते Telma लो")
    assert out == b"\xff\xfb-mp3-part-1-part-2"

    call = fake_tts.convert.await_args
    # Pronunciation override applied before TTS.
    assert "टेल्मा" in call.kwargs["text"]
    assert call.kwargs["target_language_code"] == "hi-IN"
    assert call.kwargs["speaker"] == "vidya"
    assert call.kwargs["model"] == "bulbul:v3"
    assert call.kwargs["output_audio_codec"] == "mp3"


@pytest.mark.asyncio
async def test_synthesize_rejects_unknown_voice(monkeypatch):
    fake_client = SimpleNamespace(speech_to_text=MagicMock(), text_to_speech=MagicMock())
    monkeypatch.setattr(sarvam, "_client", fake_client)
    with pytest.raises(sarvam.SarvamError):
        await sarvam.synthesize("hello", voice="meera")  # not in ALLOWED_VOICES


@pytest.mark.asyncio
async def test_synthesize_empty_audios_raises(monkeypatch):
    fake_resp = SimpleNamespace(audios=[])
    fake_tts = MagicMock()
    fake_tts.convert = AsyncMock(return_value=fake_resp)
    fake_client = SimpleNamespace(speech_to_text=MagicMock(), text_to_speech=fake_tts)
    monkeypatch.setattr(sarvam, "_client", fake_client)
    with pytest.raises(sarvam.SarvamError):
        await sarvam.synthesize("hi")


def test_fallback_is_stub():
    import asyncio

    from saathi.speech.fallback import transcribe_whisper_fallback
    with pytest.raises(NotImplementedError):
        asyncio.get_event_loop().run_until_complete(transcribe_whisper_fallback(b""))
