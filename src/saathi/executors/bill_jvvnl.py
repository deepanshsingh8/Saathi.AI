"""JVVNL bill fetch — Playwright, no login.

# RE-VALIDATE every CSS selector once Deep has loaded ``bill.jvvnl.com`` and
# walked the consumer-number entry → bill-view flow once. Selectors below are
# heuristic.

JVVNL portal is public — no login required. Caching: 1h DDB cache by
``(utility, bill_period)`` keeps duplicate Mom queries cheap.
Output amounts are in PAISE (int) to avoid float drift.
"""
from __future__ import annotations

from typing import Any

from playwright.async_api import async_playwright

from saathi.config import Settings, get_settings
from saathi.executors.medicine_1mg import ExecutorError
from saathi.storage import dynamo
from saathi.utils.logging import get_logger

log = get_logger(__name__)

JVVNL_BASE = "https://bill.jvvnl.com"


async def fetch_jvvnl_bill(consumer_number: str, *, settings: Settings | None = None) -> dict[str, Any]:
    """Returns:
        {
          consumer_number, amount_paise (int), due_date (ISO),
          bill_number, bill_period, payment_url
        }
    """
    _ = settings or get_settings()  # reserved for future per-call config

    # Cache hit?
    cached = await _cache_get(consumer_number)
    if cached:
        return cached

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(JVVNL_BASE, wait_until="domcontentloaded")
            # RE-VALIDATE: input selector.
            try:
                await page.locator("input[name='kno'], input[name='consumer_number']").first.fill(
                    consumer_number, timeout=5000,
                )
                await page.get_by_role("button", name=lambda n: "View" in (n or "")).first.click(timeout=5000)
                await page.wait_for_load_state("domcontentloaded")
                amount_text = await page.locator("text=/amount due|payable/i").first.inner_text(timeout=5000)
                due_text = await page.locator("text=/due date|last date/i").first.inner_text(timeout=5000)
                bill_no_text = await page.locator("text=/bill no/i").first.inner_text(timeout=5000)
                period_text = await page.locator("text=/bill period|month/i").first.inner_text(timeout=5000)
            except Exception as exc:  # noqa: BLE001
                raise ExecutorError(f"jvvnl scrape failed: {exc}") from exc

            payment_url = page.url
        finally:
            await browser.close()

    rupees = _parse_int(amount_text)
    due_date = _parse_date(due_text)
    bill_number = _strip_label(bill_no_text)
    bill_period = _strip_label(period_text)

    bill = {
        "consumer_number": consumer_number,
        "amount_paise": rupees * 100,
        "due_date": due_date,
        "bill_number": bill_number,
        "bill_period": bill_period,
        "payment_url": payment_url,
    }
    await _cache_put(consumer_number, bill_period, bill)
    log.info("jvvnl_bill_fetched", rupees=rupees, due=due_date, period=bill_period)
    return bill


async def _cache_get(consumer_number: str) -> dict[str, Any] | None:
    # We don't know period until we scrape, so the cache key is just the
    # latest bill we fetched for this consumer (period is part of the value).
    return await dynamo.get_bill_cache("mom", "electricity", "current")


async def _cache_put(consumer_number: str, period: str, bill: dict[str, Any]) -> None:
    await dynamo.put_bill_cache("mom", "electricity", "current", bill)


def _parse_int(text: str) -> int:
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else 0


def _parse_date(text: str) -> str:
    """Heuristic: pull the last ``DD/MM/YYYY`` or ``DD-MM-YYYY`` token. RE-VALIDATE."""
    import re
    matches = re.findall(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", text)
    return matches[-1] if matches else ""


def _strip_label(text: str) -> str:
    """Drop the prefix label (everything up to the first ':')."""
    return text.split(":", 1)[-1].strip() if ":" in text else text.strip()
