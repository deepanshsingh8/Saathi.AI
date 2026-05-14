"""1mg medicine executor — Playwright + Browserbase.

# RE-VALIDATE every CSS selector in this file once Deep has run
# scripts/manual_login_1mg.py against the real site. The selectors below are
# educated guesses based on 1mg's typical e-commerce HTML patterns — they will
# almost certainly need tweaking when the actual page is loaded. Day 7 polish.

Session persistence: ``storage_state_1mg.json`` lives in AWS Secrets Manager
under ``saathi/1mg/storage_state``. We pull it once per executor call, hydrate
the Browserbase context with it, and roll over OTP-refresh via the manual
login script when redirects to /login start happening (raise
``ExecutorError('session_expired')`` so orchestrator can escalate to Deep).
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any

import boto3
from browserbase import Browserbase
from playwright.async_api import async_playwright

from saathi.config import Settings, get_settings
from saathi.storage.s3 import get_object
from saathi.utils.logging import get_logger

log = get_logger(__name__)

ONEMG_BASE = "https://www.1mg.com"
SECRETS_KEY = "saathi/1mg/storage_state"  # AWS Secrets Manager id


class ExecutorError(RuntimeError):
    """Raised on any executor-side failure. Caught by orchestrator."""

    def __init__(self, reason: str, *, recoverable: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.recoverable = recoverable


# ─── Session bootstrap ───────────────────────────────────────────────────────


def _load_storage_state(settings: Settings) -> dict[str, Any]:
    """Pull Mom's logged-in cookies from Secrets Manager. Sync (boto3) is fine —
    this happens once per executor call and is fast."""
    sm = boto3.client("secretsmanager", region_name=settings.AWS_REGION)
    try:
        resp = sm.get_secret_value(SecretId=SECRETS_KEY)
    except Exception as exc:  # noqa: BLE001
        raise ExecutorError(f"storage_state fetch failed: {exc}") from exc
    return json.loads(resp["SecretString"])


@asynccontextmanager
async def _browser_context(settings: Settings):
    """Yield a Playwright BrowserContext attached to a Browserbase session.

    Browserbase Python SDK (v1.10.x) exposes ``Browserbase().sessions.create(...)``
    which returns a session with a ``.connectUrl``. We then connect Playwright
    over CDP to that URL.
    """
    bb = Browserbase(api_key=settings.BROWSERBASE_API_KEY)
    session = bb.sessions.create(project_id=settings.BROWSERBASE_PROJECT_ID)
    storage_state = _load_storage_state(settings)

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(session.connect_url)
        try:
            ctx = await browser.new_context(storage_state=storage_state)
            try:
                yield ctx
            finally:
                await ctx.close()
        finally:
            await browser.close()


# ─── Tools ───────────────────────────────────────────────────────────────────


async def search_medicine(query: str, *, settings: Settings | None = None) -> list[dict[str, Any]]:
    """Search 1mg by name. Returns up to 3 results.

    Selectors below are first-pass guesses. Once the manual login is done, run
    once interactively, ``await page.pause()``, and update.
    """
    s = settings or get_settings()
    async with _browser_context(s) as ctx:
        page = await ctx.new_page()
        await page.goto(f"{ONEMG_BASE}/search/all?name={query}", wait_until="domcontentloaded")
        if "/login" in page.url:
            raise ExecutorError("session_expired")

        # RE-VALIDATE: selectors below are speculative.
        cards = page.locator("[class*='ProductCard'], [data-testid*='product-card']")
        count = min(await cards.count(), 3)
        results: list[dict[str, Any]] = []
        for i in range(count):
            card = cards.nth(i)
            try:
                name = await card.locator("[class*='name'], h3, h4").first.inner_text(timeout=2000)
                price_text = await card.locator("[class*='price']").first.inner_text(timeout=2000)
                href = await card.locator("a").first.get_attribute("href")
            except Exception as exc:  # noqa: BLE001
                log.warning("search_card_parse_failed", i=i, err=str(exc))
                continue
            sku = (href or "").split("/")[-1]
            mrp = _parse_price(price_text)
            results.append({
                "sku": sku,
                "brand": (name or "").strip(),
                "dose": _extract_dose(name or ""),
                "mrp": mrp,
                "eta_hours": 24,  # 1mg standard delivery
                "cod_available": True,  # RE-VALIDATE per SKU
            })
        log.info("medicine_search_ok", q=query, n=len(results))
        return results


async def place_medicine_order(
    sku: str,
    quantity: int,
    prescription_s3_uri: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Add to cart, upload prescription image, set address, choose COD, place.

    Returns ``{order_id, eta, total}``. ``total`` is read from the live cart
    page — never invented. Raises ExecutorError on any step failure.
    """
    s = settings or get_settings()
    rx_bytes = await get_object(prescription_s3_uri)

    async with _browser_context(s) as ctx:
        page = await ctx.new_page()
        await page.goto(f"{ONEMG_BASE}/drugs/{sku}", wait_until="domcontentloaded")
        if "/login" in page.url:
            raise ExecutorError("session_expired")

        # RE-VALIDATE every selector below. AI-fallback wraps the most
        # critical actions (Day 6 polish 5).
        from saathi.executors import fallback
        try:
            await fallback.with_selector_fallback(
                page,
                primary=lambda p: p.get_by_role("button", name="Add to cart").first.click(timeout=5000),
                intent="click the Add to cart button on the product page",
                original_selector="role=button[name='Add to cart']",
                settings=s,
            )
            for _ in range(quantity - 1):
                await page.get_by_role("button", name="+").first.click(timeout=2000)

            await page.goto(f"{ONEMG_BASE}/checkout/cart", wait_until="domcontentloaded")
            await page.get_by_role("button", name="Proceed to checkout").click(timeout=5000)

            # Prescription upload
            file_input = page.locator("input[type='file']").first
            await file_input.set_input_files({
                "name": "rx.jpg",
                "mimeType": "image/jpeg",
                "buffer": rx_bytes,
            })
            await asyncio.sleep(2)  # upload settle

            # Default saved address selected; click Continue
            await page.get_by_role("button", name="Continue").click(timeout=5000)

            # COD radio
            await page.get_by_text("Cash on Delivery", exact=False).first.click(timeout=5000)
            total_loc = page.locator("[class*='order-total'], [class*='OrderTotal']").first
            total_text = await total_loc.inner_text(timeout=5000)
            total_inr = _parse_price(total_text)

            await page.get_by_role("button", name="Place order").click(timeout=5000)

            await page.wait_for_url("**/orders/**", timeout=20000)
            order_id = page.url.rstrip("/").split("/")[-1]
            eta_text = await page.locator("[class*='eta'], [class*='Eta']").first.inner_text(timeout=5000)
        except Exception as exc:  # noqa: BLE001
            log.warning("medicine_place_order_failed", err=str(exc))
            raise ExecutorError(f"place order failed: {exc}") from exc

    log.info("medicine_order_placed", order_id=order_id, total=total_inr)
    return {"order_id": order_id, "eta": eta_text.strip(), "total": total_inr}


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _parse_price(text: str) -> int:
    """Extract an integer rupee amount from a string like '₹3,240' or 'MRP ₹150.00'."""
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else 0


def _extract_dose(name: str) -> str:
    """Pick the dose token (e.g. '40 mg') out of a brand name. Heuristic."""
    parts = name.split()
    for i, p in enumerate(parts):
        if p.endswith("mg") or p.endswith("ml") or p.lower() in {"mg", "ml"}:
            if p.lower() in {"mg", "ml"} and i > 0:
                return f"{parts[i-1]} {p}"
            return p
    return ""
