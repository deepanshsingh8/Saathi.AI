"""WhatsApp Cloud API client.

Day 1 scope: outbound text only. download/upload/send_audio land Day 2.
"""
from __future__ import annotations

from typing import Any

import httpx

from saathi.config import Settings, get_settings
from saathi.utils.logging import get_logger

log = get_logger(__name__)

GRAPH_BASE = "https://graph.facebook.com/v22.0"
DEFAULT_TIMEOUT = httpx.Timeout(10.0)


class WhatsAppError(RuntimeError):
    """Raised when the Cloud API returns a non-2xx or an unexpected payload."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"whatsapp api error: {status} {body}")
        self.status = status
        self.body = body


async def send_text(
    to: str,
    body: str,
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Send a free-form text message inside the 24h customer-service window.

    Returns the WAMID (Meta message ID). Raises WhatsAppError on non-2xx.
    Logs structured request/response without the access token.
    """
    s = settings or get_settings()
    url = f"{GRAPH_BASE}/{s.WA_PHONE_ID}/messages"
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    headers = {
        "Authorization": f"Bearer {s.WA_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
    try:
        resp = await http.post(url, json=payload, headers=headers)
    finally:
        if owns_client:
            await http.aclose()

    if resp.status_code >= 300:
        log.warning("whatsapp_send_failed", status=resp.status_code, body=resp.text[:500])
        raise WhatsAppError(resp.status_code, resp.text)

    data = resp.json()
    try:
        wamid = data["messages"][0]["id"]
    except (KeyError, IndexError, TypeError) as exc:
        log.warning("whatsapp_unexpected_payload", payload=data)
        raise WhatsAppError(resp.status_code, resp.text) from exc

    log.info("whatsapp_send_ok", to=_mask(to), wamid=wamid, body_len=len(body))
    return wamid


async def download_media(
    media_id: str,
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[bytes, str]:
    """Two-step Cloud API media fetch.

    1. ``GET /v22.0/{media_id}`` (Bearer auth) → ``{url, mime_type, ...}``.
    2. ``GET <url>`` (Bearer auth required) → audio bytes.

    The URL from step 1 is short-lived (~5 min) — call this promptly from the
    worker, not deferred. Returns ``(bytes, mime_type)``.
    """
    s = settings or get_settings()
    headers = {"Authorization": f"Bearer {s.WA_ACCESS_TOKEN}"}

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
    try:
        meta_resp = await http.get(f"{GRAPH_BASE}/{media_id}", headers=headers)
        if meta_resp.status_code >= 300:
            raise WhatsAppError(meta_resp.status_code, meta_resp.text)
        meta = meta_resp.json()
        media_url = meta.get("url")
        mime_type = meta.get("mime_type", "application/octet-stream")
        if not media_url:
            raise WhatsAppError(meta_resp.status_code, "missing url in media metadata")

        bin_resp = await http.get(media_url, headers=headers)
        if bin_resp.status_code >= 300:
            raise WhatsAppError(bin_resp.status_code, bin_resp.text[:300])
        data = bin_resp.content
    finally:
        if owns_client:
            await http.aclose()

    log.info("whatsapp_media_fetched", media_id=media_id, mime=mime_type, bytes=len(data))
    return data, mime_type


async def upload_media(
    data: bytes,
    mime_type: str,
    *,
    filename: str = "voice.mp3",
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Multipart POST to ``/v22.0/{phone_id}/media``. Returns Meta media ID.

    Use ``audio/mpeg`` for MP3 outbound (Sarvam Bulbul output). Don't use
    ``audio/mp3`` — Meta is picky.
    """
    s = settings or get_settings()
    url = f"{GRAPH_BASE}/{s.WA_PHONE_ID}/media"
    headers = {"Authorization": f"Bearer {s.WA_ACCESS_TOKEN}"}
    files = {"file": (filename, data, mime_type)}
    form = {"messaging_product": "whatsapp", "type": mime_type}

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
    try:
        resp = await http.post(url, headers=headers, files=files, data=form)
    finally:
        if owns_client:
            await http.aclose()

    if resp.status_code >= 300:
        log.warning("whatsapp_upload_failed", status=resp.status_code, body=resp.text[:300])
        raise WhatsAppError(resp.status_code, resp.text)

    body = resp.json()
    media_id = body.get("id")
    if not media_id:
        raise WhatsAppError(resp.status_code, "missing id in upload response")
    log.info("whatsapp_uploaded", media_id=media_id, bytes=len(data), mime=mime_type)
    return media_id


async def send_buttons(
    to: str,
    body: str,
    buttons: list[str],
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Send an interactive reply-buttons message.

    Cloud API caps buttons at 3, each title ≤20 chars. We stable-id them
    ``btn_<index>`` so the inbound interactive callback is parseable without
    looking up state.
    """
    if not 1 <= len(buttons) <= 3:
        raise WhatsAppError(0, f"buttons must be 1–3, got {len(buttons)}")
    if any(len(b) > 20 for b in buttons):
        raise WhatsAppError(0, "button title too long (max 20 chars)")

    s = settings or get_settings()
    url = f"{GRAPH_BASE}/{s.WA_PHONE_ID}/messages"
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": f"btn_{i}", "title": title}}
                    for i, title in enumerate(buttons)
                ]
            },
        },
    }
    headers = {"Authorization": f"Bearer {s.WA_ACCESS_TOKEN}", "Content-Type": "application/json"}

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
    try:
        resp = await http.post(url, json=payload, headers=headers)
    finally:
        if owns_client:
            await http.aclose()

    if resp.status_code >= 300:
        raise WhatsAppError(resp.status_code, resp.text)
    data = resp.json()
    try:
        wamid = data["messages"][0]["id"]
    except (KeyError, IndexError, TypeError) as exc:
        raise WhatsAppError(resp.status_code, resp.text) from exc
    log.info("whatsapp_buttons_sent", to=_mask(to), wamid=wamid, n=len(buttons))
    return wamid


async def send_image(
    to: str,
    *,
    media_id: str | None = None,
    link: str | None = None,
    caption: str | None = None,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Send a previously-uploaded image (by media_id) or a public image URL.

    Used for forwarding bill-payment receipts from Deep to Mom (Day 5 polish).
    Exactly one of ``media_id`` / ``link`` must be set.
    """
    if (media_id is None) == (link is None):
        raise WhatsAppError(0, "exactly one of media_id/link required")
    s = settings or get_settings()
    url = f"{GRAPH_BASE}/{s.WA_PHONE_ID}/messages"
    image_payload: dict[str, Any] = {}
    if media_id:
        image_payload["id"] = media_id
    if link:
        image_payload["link"] = link
    if caption:
        image_payload["caption"] = caption
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": image_payload,
    }
    headers = {"Authorization": f"Bearer {s.WA_ACCESS_TOKEN}", "Content-Type": "application/json"}

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
    try:
        resp = await http.post(url, json=payload, headers=headers)
    finally:
        if owns_client:
            await http.aclose()

    if resp.status_code >= 300:
        raise WhatsAppError(resp.status_code, resp.text)
    data = resp.json()
    try:
        wamid = data["messages"][0]["id"]
    except (KeyError, IndexError, TypeError) as exc:
        raise WhatsAppError(resp.status_code, resp.text) from exc
    log.info("whatsapp_image_sent", to=_mask(to), wamid=wamid)
    return wamid


async def send_audio(
    to: str,
    media_id: str,
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Send an audio message referencing a previously-uploaded media id."""
    s = settings or get_settings()
    url = f"{GRAPH_BASE}/{s.WA_PHONE_ID}/messages"
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "audio",
        "audio": {"id": media_id},
    }
    headers = {
        "Authorization": f"Bearer {s.WA_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
    try:
        resp = await http.post(url, json=payload, headers=headers)
    finally:
        if owns_client:
            await http.aclose()

    if resp.status_code >= 300:
        raise WhatsAppError(resp.status_code, resp.text)

    data = resp.json()
    try:
        wamid = data["messages"][0]["id"]
    except (KeyError, IndexError, TypeError) as exc:
        raise WhatsAppError(resp.status_code, resp.text) from exc

    log.info("whatsapp_audio_sent", to=_mask(to), wamid=wamid, media_id=media_id)
    return wamid


def _mask(num: str) -> str:
    """Mask middle digits of an E.164 number for logs (privacy)."""
    if len(num) <= 6:
        return num
    return f"{num[:4]}…{num[-2:]}"
