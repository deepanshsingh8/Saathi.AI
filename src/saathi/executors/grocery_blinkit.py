"""Blinkit grocery executor — Playwright + Browserbase.

# RE-VALIDATE every CSS selector once Deep has run scripts/manual_login_blinkit.py
# against the real site. Selectors are first-pass guesses based on Blinkit's
# typical e-commerce HTML.

Same shape as ``medicine_1mg.py``: persistent storage_state from Secrets Manager,
search → cart → checkout COD. PIN serviceability check before promising ETA.
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
from saathi.executors.medicine_1mg import ExecutorError
from saathi.utils.logging import get_logger

log = get_logger(__name__)

BLINKIT_BASE = "https://blinkit.com"
SECRETS_KEY = "saathi/blinkit/storage_state"

# In-process cart state. Single-user means we can keep this in-memory; on
# multi-user this would live in DDB session.
_cart_state: dict[str, Any] = {"items": [], "total": 0, "eta_minutes": 0}


def _load_storage_state(settings: Settings) -> dict[str, Any]:
    sm = boto3.client("secretsmanager", region_name=settings.AWS_REGION)
    try:
        resp = sm.get_secret_value(SecretId=SECRETS_KEY)
    except Exception as exc:  # noqa: BLE001
        raise ExecutorError(f"blinkit storage_state fetch failed: {exc}") from exc
    return json.loads(resp["SecretString"])


@asynccontextmanager
async def _browser_context(settings: Settings):
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


async def check_pin_serviceable(pin: str, *, settings: Settings | None = None) -> bool:
    """Hit Blinkit's serviceability check before promising ETA."""
    s = settings or get_settings()
    async with _browser_context(s) as ctx:
        page = await ctx.new_page()
        await page.goto(f"{BLINKIT_BASE}/?pin={pin}", wait_until="domcontentloaded")
        # RE-VALIDATE: serviceability indicator selector.
        try:
            unserviceable_loc = page.locator(
                "text=/unserviceable|not available|not serviceable/i"
            ).first
            unserviceable = await unserviceable_loc.is_visible(timeout=2000)
        except Exception:  # noqa: BLE001
            unserviceable = False
        return not unserviceable


async def search_blinkit(query: str, *, settings: Settings | None = None) -> list[dict[str, Any]]:
    s = settings or get_settings()
    async with _browser_context(s) as ctx:
        page = await ctx.new_page()
        await page.goto(f"{BLINKIT_BASE}/s/?q={query}", wait_until="domcontentloaded")
        if "/login" in page.url:
            raise ExecutorError("session_expired")

        # RE-VALIDATE selectors below.
        cards = page.locator("[class*='Product__'], [data-test*='product']")
        count = min(await cards.count(), 3)
        results: list[dict[str, Any]] = []
        for i in range(count):
            card = cards.nth(i)
            try:
                name = await card.locator("[class*='name'], h3").first.inner_text(timeout=2000)
                price_text = await card.locator("[class*='price']").first.inner_text(timeout=2000)
                pack_loc = card.locator("[class*='quantity'], [class*='size']").first
                pack = await pack_loc.inner_text(timeout=2000)
                href = await card.locator("a").first.get_attribute("href")
            except Exception as exc:  # noqa: BLE001
                log.warning("blinkit_card_parse_failed", i=i, err=str(exc))
                continue
            results.append({
                "sku": (href or "").rsplit("/", 1)[-1],
                "name": (name or "").strip(),
                "pack_size": (pack or "").strip(),
                "price": _parse_price(price_text or ""),
                "in_stock": True,
            })
        log.info("blinkit_search_ok", q=query, n=len(results))
        return results


async def add_to_cart(sku: str, quantity: int, *, settings: Settings | None = None) -> dict[str, Any]:
    """Navigate to product page, click +. Returns updated in-memory cart."""
    s = settings or get_settings()
    async with _browser_context(s) as ctx:
        page = await ctx.new_page()
        await page.goto(f"{BLINKIT_BASE}/p/{sku}", wait_until="domcontentloaded")
        if "/login" in page.url:
            raise ExecutorError("session_expired")
        try:
            for _ in range(quantity):
                await page.get_by_role("button", name="+").first.click(timeout=3000)
                await asyncio.sleep(0.3)
        except Exception as exc:  # noqa: BLE001
            raise ExecutorError(f"add_to_cart failed: {exc}") from exc

    _cart_state["items"].append({"sku": sku, "quantity": quantity})
    return _cart_state


async def get_cart(*, settings: Settings | None = None) -> dict[str, Any]:
    """Read cart from the live page DOM, never invent the total."""
    s = settings or get_settings()
    async with _browser_context(s) as ctx:
        page = await ctx.new_page()
        await page.goto(f"{BLINKIT_BASE}/checkout", wait_until="domcontentloaded")
        if "/login" in page.url:
            raise ExecutorError("session_expired")
        try:
            total_loc = page.locator("[class*='total'], [data-test*='total']").first
            eta_loc = page.locator("[class*='eta'], [class*='delivery-time']").first
            total_text = await total_loc.inner_text(timeout=5000)
            eta_text = await eta_loc.inner_text(timeout=5000)
        except Exception as exc:  # noqa: BLE001
            raise ExecutorError(f"get_cart failed: {exc}") from exc

    total = _parse_price(total_text)
    eta = _parse_minutes(eta_text)
    _cart_state["total"] = total
    _cart_state["eta_minutes"] = eta
    return _cart_state


async def checkout_cod(*, settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    async with _browser_context(s) as ctx:
        page = await ctx.new_page()
        await page.goto(f"{BLINKIT_BASE}/checkout", wait_until="domcontentloaded")
        if "/login" in page.url:
            raise ExecutorError("session_expired")
        from saathi.executors import fallback
        try:
            await fallback.with_selector_fallback(
                page,
                primary=lambda p: p.get_by_text("Cash on Delivery", exact=False).first.click(timeout=5000),
                intent="select the Cash on Delivery payment method",
                original_selector="text=Cash on Delivery",
                settings=s,
            )
            total_text = await page.locator("[class*='total']").first.inner_text(timeout=5000)
            total = _parse_price(total_text)
            await fallback.with_selector_fallback(
                page,
                primary=lambda p: p.get_by_role(
                    "button", name=lambda n: "Place" in (n or ""),
                ).first.click(timeout=5000),
                intent="click the Place order / Confirm order button at checkout",
                original_selector="role=button[name~=Place]",
                settings=s,
            )
            await page.wait_for_url("**/order/**", timeout=20000)
            order_id = page.url.rstrip("/").split("/")[-1]
            eta_text = await page.locator("[class*='eta']").first.inner_text(timeout=5000)
        except Exception as exc:  # noqa: BLE001
            raise ExecutorError(f"checkout_cod failed: {exc}") from exc

    log.info("blinkit_order_placed", order_id=order_id, total=total)
    _cart_state["items"] = []
    return {"order_id": order_id, "eta": eta_text.strip(), "total": total}


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _parse_price(text: str) -> int:
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else 0


def _parse_minutes(text: str) -> int:
    """Pull minute count from strings like '12 mins', '15-20 min'."""
    digits = ""
    for c in text:
        if c.isdigit():
            digits += c
        elif digits:
            break
    return int(digits) if digits else 0
