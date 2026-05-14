"""Tests for storage/s3.py — mocked aioboto3 client.

We do not pull in `moto` for one tested module. The s3 module's surface is
small enough to monkey-patch the session's `client(...)` async-context-manager.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from saathi.storage import s3


class _FakeStreamingBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self) -> bytes:
        return self._data


def _patch_s3_client(monkeypatch, fake_client: Any) -> None:
    """Replace s3.get_session() with a stub that yields ``fake_client`` from ``client(...)``."""
    @asynccontextmanager
    async def _ctx(_self, _name: str, **_kw: Any):
        yield fake_client

    fake_session = MagicMock()
    fake_session.client = _ctx.__get__(fake_session)  # bind as method
    monkeypatch.setattr(s3, "get_session", lambda: fake_session)


@pytest.mark.asyncio
async def test_put_voice_uploads_and_returns_uri(monkeypatch):
    fake_client = MagicMock()
    fake_client.put_object = AsyncMock(return_value={})
    _patch_s3_client(monkeypatch, fake_client)

    uri = await s3.put_voice("mom", "inbound", b"oggdata", ext="oga")
    assert uri.startswith("s3://saathi-media-test/mom/inbound/")
    assert uri.endswith(".oga")

    call = fake_client.put_object.await_args
    assert call.kwargs["Bucket"] == "saathi-media-test"
    assert call.kwargs["Body"] == b"oggdata"
    assert call.kwargs["ContentType"] == "audio/ogg"


@pytest.mark.asyncio
async def test_get_object_reads_streaming_body(monkeypatch):
    fake_client = MagicMock()
    fake_client.get_object = AsyncMock(return_value={"Body": _FakeStreamingBody(b"payload")})
    _patch_s3_client(monkeypatch, fake_client)

    out = await s3.get_object("s3://saathi-media-test/mom/inbound/123.oga")
    assert out == b"payload"

    call = fake_client.get_object.await_args
    assert call.kwargs["Bucket"] == "saathi-media-test"
    assert call.kwargs["Key"] == "mom/inbound/123.oga"


def test_parse_rejects_non_s3_uri():
    with pytest.raises(ValueError):
        s3._parse("https://example.com/x")


def test_parse_rejects_missing_key():
    with pytest.raises(ValueError):
        s3._parse("s3://bucket-only")


def test_content_type_known_and_default():
    assert s3._content_type("oga") == "audio/ogg"
    assert s3._content_type("mp3") == "audio/mpeg"
    assert s3._content_type("xyz") == "application/octet-stream"
