"""Haiku 4.5 intent classifier.

One-shot JSON classification — uses Anthropic SDK directly (lighter than
Agent SDK for this use). Routes via Bedrock when ``USE_BEDROCK=true``,
else via api.anthropic.com.

Output schema (always returned, even on parse failure):
    {"intent": str, "confidence": float, "slots": dict}
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from anthropic import AsyncAnthropic, AsyncAnthropicBedrock

from saathi.config import Settings, get_settings
from saathi.llm.prompts import INTENT_CLASSIFIER
from saathi.utils.logging import get_logger

log = get_logger(__name__)

VALID_INTENTS = {"medicine", "grocery", "bill", "chitchat", "unknown"}
UNKNOWN: dict[str, Any] = {"intent": "unknown", "confidence": 0.0, "slots": {}}


@lru_cache(maxsize=1)
def _client(use_bedrock: bool) -> AsyncAnthropic | AsyncAnthropicBedrock:
    s = get_settings()
    if use_bedrock:
        return AsyncAnthropicBedrock(aws_region=s.AWS_REGION)
    return AsyncAnthropic(api_key=s.ANTHROPIC_API_KEY)


async def classify(transcript: str, *, settings: Settings | None = None) -> dict[str, Any]:
    """Classify a Hindi/Hinglish transcript into one of VALID_INTENTS."""
    s = settings or get_settings()
    client = _client(s.USE_BEDROCK)
    model = s.BEDROCK_MODEL_HAIKU if s.USE_BEDROCK else "claude-haiku-4-5-20251001"

    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=200,
            temperature=0.0,
            system=INTENT_CLASSIFIER,
            messages=[{"role": "user", "content": transcript}],
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("intent_call_failed", err=str(exc))
        return UNKNOWN

    text = _extract_text(resp)
    parsed = _parse_json(text)
    if parsed is None or parsed.get("intent") not in VALID_INTENTS:
        log.warning("intent_parse_failed", raw=text[:200])
        return UNKNOWN

    parsed.setdefault("confidence", 0.0)
    parsed.setdefault("slots", {})
    log.info("intent_classified", intent=parsed["intent"], confidence=parsed["confidence"])
    return parsed


def _extract_text(resp: Any) -> str:
    """Pull the first text block out of an Anthropic response."""
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def _parse_json(text: str) -> dict[str, Any] | None:
    """Tolerant JSON extraction — strips a leading ```json fence if present."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        return None
    return out if isinstance(out, dict) else None
