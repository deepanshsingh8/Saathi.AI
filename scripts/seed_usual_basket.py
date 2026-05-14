"""Seed Mom's usual grocery basket into DDB.

Usage:
    uv run python scripts/seed_usual_basket.py --file scripts/data/usual_basket.json

Template at ``scripts/data/usual_basket.template.json``.
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
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("expected list of items at top level or under 'items'")
    await dynamo.put_usual_basket(items)
    print(f"✓ Wrote basket#default ({len(items)} items)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True, type=Path)
    args = ap.parse_args()
    if not args.file.exists():
        print(f"ERROR: {args.file} does not exist", file=sys.stderr)
        sys.exit(1)
    asyncio.run(seed(args.file))


if __name__ == "__main__":
    main()
