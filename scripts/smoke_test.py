"""End-to-end smoke test against the deployed Saathi instance.

Usage:
    uv run python scripts/smoke_test.py --flow medicine --dry-run
    uv run python scripts/smoke_test.py --flow grocery
    uv run python scripts/smoke_test.py --flow bill --dry-run

Sends a recorded fixture voice note from Deep's dev WhatsApp number to Saathi
and waits for the round-trip. ``--dry-run`` causes the executor to skip the
final "place order" click (set via env var the executor reads).

This is for Day 3+ — meaningful only after the Lightsail box is live and Meta
webhook is configured (docs/HUMAN_SETUP.md §9, §11).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx

FIXTURES = {
    "medicine": "tests/fixtures/mom_medicine.oga",
    "grocery": "tests/fixtures/mom_grocery.oga",
    "bill": "tests/fixtures/mom_bill.oga",
}


async def send_fixture(flow: str, dev_phone: str, *, dry_run: bool) -> None:
    fixture = Path(FIXTURES[flow])
    if not fixture.exists():
        print(f"ERROR: fixture {fixture} missing — record one with Mom first.", file=sys.stderr)
        sys.exit(1)

    token = os.environ["WA_ACCESS_TOKEN"]
    phone_id = os.environ["WA_PHONE_ID"]
    if dry_run:
        os.environ["SAATHI_DRY_RUN"] = "1"

    # Step 1: upload the audio to Cloud API. Read into memory upfront so we
    # don't hold a file handle across an async network call (ASYNC230).
    audio_bytes = fixture.read_bytes()
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"https://graph.facebook.com/v22.0/{phone_id}/media",
            headers={"Authorization": f"Bearer {token}"},
            data={"messaging_product": "whatsapp", "type": "audio/ogg"},
            files={"file": (fixture.name, audio_bytes, "audio/ogg")},
        )
        r.raise_for_status()
        media_id = r.json()["id"]

        # Step 2: send as audio message.
        r = await client.post(
            f"https://graph.facebook.com/v22.0/{phone_id}/messages",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "messaging_product": "whatsapp",
                "to": dev_phone,
                "type": "audio",
                "audio": {"id": media_id},
            },
        )
        r.raise_for_status()
        print(f"✓ Sent fixture for {flow!r}. Watch the box logs for the round-trip.")
        print("  (sudo journalctl -u saathi -f on Lightsail)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--flow", required=True, choices=["medicine", "grocery", "bill"])
    ap.add_argument(
        "--dev-phone", default=os.environ.get("DEV_PHONE", ""),
        help="E.164 phone to send from (your dev number, NOT Mom's). Falls back to DEV_PHONE env.",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="Sets SAATHI_DRY_RUN=1; executors skip the final place-order step.")
    args = ap.parse_args()
    if not args.dev_phone:
        print("ERROR: pass --dev-phone or set DEV_PHONE env", file=sys.stderr)
        sys.exit(1)

    asyncio.run(send_fixture(args.flow, args.dev_phone, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
