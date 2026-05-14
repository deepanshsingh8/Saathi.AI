"""S3 voice-and-media archival.

Single shared aioboto3 session, injected via FastAPI dependency or imported
directly in worker code. Bucket is encrypted at the bucket level (SSE-KMS) —
this module assumes that and does not set per-object encryption.
"""
from __future__ import annotations

import time
from typing import Literal

import aioboto3

from saathi.config import get_settings
from saathi.utils.logging import get_logger

log = get_logger(__name__)

VoiceKind = Literal["inbound", "outbound", "prescription", "receipt", "system"]

_session: aioboto3.Session | None = None


def get_session() -> aioboto3.Session:
    """Lazy global aioboto3 session. One per process.

    Cheap to call — only constructs once. Tests can monkeypatch the module-level
    `_session` symbol to inject a fake.
    """
    global _session
    if _session is None:
        _session = aioboto3.Session(region_name=get_settings().AWS_REGION)
    return _session


def _key(user: str, kind: VoiceKind, ext: str) -> str:
    return f"{user}/{kind}/{int(time.time() * 1000)}.{ext}"


async def put_voice(user: str, kind: VoiceKind, data: bytes, ext: str = "oga") -> str:
    """Upload audio bytes to ``s3://{S3_BUCKET}/{user}/{kind}/{ts}.{ext}``.

    Returns the ``s3://`` URI.
    """
    s = get_settings()
    key = _key(user, kind, ext)
    session = get_session()
    async with session.client("s3") as client:
        await client.put_object(
            Bucket=s.S3_BUCKET,
            Key=key,
            Body=data,
            ContentType=_content_type(ext),
        )
    uri = f"s3://{s.S3_BUCKET}/{key}"
    log.info("s3_put_voice", uri=uri, kind=kind, bytes=len(data))
    return uri


async def get_object(s3_uri: str) -> bytes:
    """Fetch an object by its s3:// URI."""
    bucket, key = _parse(s3_uri)
    session = get_session()
    async with session.client("s3") as client:
        resp = await client.get_object(Bucket=bucket, Key=key)
        body = await resp["Body"].read()
    return body


def _parse(s3_uri: str) -> tuple[str, str]:
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"not an s3:// uri: {s3_uri}")
    rest = s3_uri[len("s3://"):]
    bucket, _, key = rest.partition("/")
    if not bucket or not key:
        raise ValueError(f"malformed s3 uri: {s3_uri}")
    return bucket, key


def _content_type(ext: str) -> str:
    return {
        "oga": "audio/ogg",
        "ogg": "audio/ogg",
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "pdf": "application/pdf",
    }.get(ext.lower(), "application/octet-stream")
