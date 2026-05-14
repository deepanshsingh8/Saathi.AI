"""One-time manual OTP login for Blinkit. See manual_login_1mg.py.

Usage:
    uv run python scripts/manual_login_blinkit.py
    aws secretsmanager create-secret \\
        --name saathi/blinkit/storage_state \\
        --region ap-south-1 \\
        --secret-string file://storage_state_blinkit.json
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path("storage_state_blinkit.json")
BLINKIT = "https://blinkit.com"


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(BLINKIT, wait_until="domcontentloaded")
        print("\n" + "=" * 60)
        print("Mom: log in with phone+OTP. Allow location for Jaipur PIN.")
        print("Once you can see her usual neighborhood and items, press Enter here.")
        print("=" * 60)
        input("Press Enter when logged in… ")
        await ctx.storage_state(path=str(OUT))
        print(f"\n✓ Saved storage state to {OUT.resolve()}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
