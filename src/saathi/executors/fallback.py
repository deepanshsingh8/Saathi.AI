"""AI-powered selector fallback for Playwright actions (Day 6 polish 5).

When a CSS selector breaks (Blinkit redesigns a button, 1mg renames a class),
the executor previously failed and Saathi escalated to Deep. This module wraps
a primary Playwright action with a one-shot LLM-driven retry: on
``PlaywrightTimeoutError`` we capture a snippet of the page HTML, ask Sonnet
("which CSS selector matches this intent?"), and try that.

This is a poor-man's Stagehand: same recovery, no extra dep. Slower (~2s
LLM round-trip) but cheap to add.

# RE-VALIDATE the prompt and HTML truncation policy after first real recovery.
# Initial reasonable defaults — might over-eagerly recover on legitimate
# missing elements (out-of-stock items, region restrictions). Day 7.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from anthropic import AsyncAnthropic, AsyncAnthropicBedrock
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from saathi.config import Settings, get_settings
from saathi.utils.logging import get_logger

log = get_logger(__name__)

MAX_HTML_CHARS = 8000
SELECTOR_PROMPT = """You see a snippet of HTML from an Indian e-commerce site.
The user wanted to perform this action: "{intent}".
Their original CSS selector was "{original_selector}" but it returned no match.
Find a CSS selector in the HTML that matches the same intent and reply with
ONLY the selector string — no quotes, no prose, no markdown. If no selector
matches, reply with the literal token NO_MATCH.

HTML:
```
{html}
```
"""


async def with_selector_fallback(
    page: Page,
    *,
    primary: Callable[[Page], Awaitable[Any]],
    intent: str,
    original_selector: str,
    settings: Settings | None = None,
) -> Any:
    """Run ``primary(page)``. On Playwright timeout, ask Sonnet for a new
    selector and click it once.

    Pattern in executor:
        await fallback.with_selector_fallback(
            page,
            primary=lambda p: p.get_by_role("button", name="Add to cart").first.click(timeout=5000),
            intent="click the Add to cart button on this product page",
            original_selector="role=button[name='Add to cart']",
        )
    """
    try:
        return await primary(page)
    except PlaywrightTimeoutError as exc:
        log.warning("selector_fallback_triggered", intent=intent, err=str(exc))

    s = settings or get_settings()
    html = await page.content()
    snippet = html[:MAX_HTML_CHARS]

    selector = await _ask_for_selector(s, intent, original_selector, snippet)
    if selector == "NO_MATCH":
        log.warning("selector_fallback_no_match", intent=intent)
        raise PlaywrightTimeoutError(f"no AI fallback selector for {intent!r}")

    log.info("selector_fallback_trying", selector=selector, intent=intent)
    try:
        await page.locator(selector).first.click(timeout=5000)
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("selector_fallback_failed", selector=selector, err=str(exc))
        raise PlaywrightTimeoutError(f"AI fallback selector {selector!r} also failed") from exc


async def _ask_for_selector(
    settings: Settings, intent: str, original: str, html: str,
) -> str:
    """Ask Sonnet for a single CSS selector. Returns the raw token (or NO_MATCH)."""
    if settings.USE_BEDROCK:
        client: AsyncAnthropic | AsyncAnthropicBedrock = AsyncAnthropicBedrock(
            aws_region=settings.AWS_REGION,
        )
        model = settings.BEDROCK_MODEL_SONNET
    else:
        client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        model = "claude-sonnet-4-6"

    prompt = SELECTOR_PROMPT.format(intent=intent, original_selector=original, html=html)
    try:
        resp = await client.messages.create(
            model=model, max_tokens=200, temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("selector_fallback_llm_failed", err=str(exc))
        return "NO_MATCH"

    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "text":
            return block.text.strip().splitlines()[0].strip()
    return "NO_MATCH"
