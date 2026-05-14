"""Seed Mom's profile + medicines + usual_basket into DynamoDB.

Usage:
    uv run python scripts/seed_profile.py --file ~/saathi-private/profile.json

The JSON file shape is documented in docs/HUMAN_SETUP.md §7. This script is
idempotent — re-running it overwrites existing items.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from saathi.storage import dynamo


async def seed(file_path: Path) -> None:
    data = json.loads(file_path.read_text(encoding="utf-8"))

    # Profile
    profile = {k: v for k, v in data.items() if k not in {"medicines", "usual_basket"}}
    await dynamo.put_profile(profile)
    print(f"  ✓ profile written: {profile.get('name', '?')}")

    # Per-medicine items (so the orchestrator can list_medicines())
    for med in data.get("medicines", []):
        sku = med.get("name", "").lower().replace(" ", "_")
        if not sku:
            continue
        await _put_med(sku, med)
        print(f"  ✓ med#{sku}")

    # Usual basket
    basket = data.get("usual_basket", [])
    if basket:
        await dynamo.put_usual_basket(basket)
        print(f"  ✓ basket#default ({len(basket)} items)")


async def _put_med(sku: str, med: dict) -> None:
    """Write a med item via the same low-level pattern dynamo uses."""
    import time

    import aioboto3

    from saathi.config import get_settings

    s = get_settings()
    session = aioboto3.Session(region_name=s.AWS_REGION)
    item = {**med, "pk": "mom", "sk": f"med#{sku}", "updated_at": int(time.time())}
    async with session.resource("dynamodb", region_name=s.AWS_REGION) as ddb:
        table = await ddb.Table(s.DDB_TABLE)
        await table.put_item(Item=item)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True, type=Path, help="Path to profile.json")
    args = ap.parse_args()

    if not args.file.exists():
        print(f"ERROR: {args.file} does not exist", file=sys.stderr)
        sys.exit(1)

    print(f"Seeding from {args.file}…")
    asyncio.run(seed(args.file))
    print("Done.")


if __name__ == "__main__":
    main()
