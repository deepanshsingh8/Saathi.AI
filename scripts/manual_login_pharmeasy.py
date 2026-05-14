"""One-time manual OTP login for PharmEasy (1mg backup). See manual_login_1mg.py.

Usage:
    uv run python scripts/manual_login_pharmeasy.py
    aws secretsmanager create-secret \\
        --name saathi/pharmeasy/storage_state \\
        --region ap-south-1 \\
        --secret-string file://storage_state_pharmeasy.json
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path("storage_state_pharmeasy.json")
PE = "https://pharmeasy.in"


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(PE, wait_until="domcontentloaded")
        print("\n" + "=" * 60)
        print("Mom: log in with phone+OTP. Press Enter here when done.")
        print("=" * 60)
        input("Press Enter when logged in… ")
        await ctx.storage_state(path=str(OUT))
        print(f"\n✓ Saved storage state to {OUT.resolve()}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
