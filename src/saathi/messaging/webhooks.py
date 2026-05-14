"""Inbound webhook parsing + Meta HMAC signature verification.

Day 1: text-only message extraction. Audio/interactive arrive Day 2/3.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any


def verify_signature(body: bytes, header: str | None, app_secret: str) -> bool:
    """Verify X-Hub-Signature-256.

    Header format: 'sha256=<hex>'. Returns False if the header is missing,
    malformed, or doesn't match. Uses constant-time comparison.
    """
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    provided = header.split("=", 1)[1]
    return hmac.compare_digest(expected, provided)


def extract_message(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the first inbound message from a Cloud API webhook payload.

    Meta also sends `statuses` updates with no `messages` key — we ignore
    those (return None). Defensive against shape variations.
    """
    try:
        value = payload["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError, TypeError):
        return None
    messages = value.get("messages")
    if not messages:
        return None
    return messages[0]
