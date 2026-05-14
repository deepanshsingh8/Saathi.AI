"""One-time manual OTP login for 1mg.

Mom holds her phone, enters OTP. Run on Deep's laptop (NOT the Lightsail box —
needs a real Chrome window). Saves storage_state to a local file; upload to
AWS Secrets Manager afterwards (see docs/HUMAN_SETUP.md §8).

Usage:
    uv run python scripts/manual_login_1mg.py
    # → opens Chrome, Mom logs in, press Enter when "My Account" is visible.

    aws secretsmanager create-secret \\
        --name saathi/1mg/storage_state \\
        --region ap-south-1 \\
        --secret-string file://storage_state_1mg.json
    rm storage_state_1mg.json
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path("storage_state_1mg.json")
ONEMG = "https://www.1mg.com"


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(ONEMG, wait_until="domcontentloaded")
        print()
        print("=" * 60)
        print("Hand the laptop to Mom. She should:")
        print("  1. Click 'Login / Sign Up' at the top right.")
        print("  2. Enter her phone number, get OTP, log in.")
        print("  3. Once she sees her name / 'My Account' in the header,")
        print("     press Enter HERE in the terminal.")
        print("=" * 60)
        input("Press Enter when logged in… ")

        await ctx.storage_state(path=str(OUT))
        print(f"\n✓ Saved storage state to {OUT.resolve()}")
        print("Now upload to Secrets Manager (see docs/HUMAN_SETUP.md §8.1).")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
