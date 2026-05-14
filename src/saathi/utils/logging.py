"""Structured JSON logger.

CloudWatch picks up stdout. Always emit a single JSON object per line.
Never log voice content (privacy); log a transcript hash if needed.

Usage:
    from saathi.utils.logging import get_logger
    log = get_logger(__name__)
    log.info("stt_done", conv_id=cid, latency_ms=812, transcript_len=42)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": int(time.time() * 1000),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        extras = getattr(record, "extras", None)
        if isinstance(extras, dict):
            payload.update(extras)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


_RESERVED = {"exc_info", "stack_info", "stacklevel"}


class _StructuredAdapter(logging.LoggerAdapter):
    def process(self, msg: Any, kwargs: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        extras = {k: v for k, v in kwargs.items() if k not in _RESERVED}
        forward = {k: kwargs[k] for k in _RESERVED if k in kwargs}
        forward["extra"] = {"extras": extras}
        return msg, forward


_configured = False


def _configure_root() -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    _configured = True


def get_logger(name: str) -> _StructuredAdapter:
    _configure_root()
    return _StructuredAdapter(logging.getLogger(name), {})
