"""Pre-render the static Hindi voice clips (interim acks + failure voices),
upload to S3, register Meta media_ids, and cache the ids in DDB.

Run ONCE after first deploy, and again whenever ``messaging/templates.py``
gets new entries.

Usage:
    uv run python scripts/prerender_system_voices.py

Reads SARVAM + WA + AWS env from ``.env`` like the main app.

DDB layout:
    pk=mom, sk=system_voice#<key>     {media_id, s3_uri, text, generated_at}
"""
from __future__ import annotations

import asyncio
import time

import aioboto3

from saathi.config import get_settings
from saathi.messaging import whatsapp
from saathi.messaging.templates import FAILURE_VOICES, INTERIM_ACKS, INTERIM_ACKS_SLOW
from saathi.speech import sarvam
from saathi.storage import s3 as s3mod


async def render_one(key: str, text: str) -> dict:
    audio = await sarvam.synthesize(text)
    s3_uri = await s3mod.put_voice("system", "outbound", audio, ext="mp3")
    media_id = await whatsapp.upload_media(audio, "audio/mpeg", filename=f"{key}.mp3")
    return {
        "media_id": media_id,
        "s3_uri": s3_uri,
        "text": text,
        "generated_at": int(time.time()),
    }


async def cache_to_ddb(key: str, payload: dict) -> None:
    s = get_settings()
    session = aioboto3.Session(region_name=s.AWS_REGION)
    async with session.resource("dynamodb", region_name=s.AWS_REGION) as ddb:
        table = await ddb.Table(s.DDB_TABLE)
        await table.put_item(Item={**payload, "pk": "mom", "sk": f"system_voice#{key}"})


async def main() -> None:
    work: dict[str, str] = {}
    work.update({f"failure:{k}": v for k, v in FAILURE_VOICES.items() if "{" not in v})
    # Skip parameterised failures (`{item}`, `{service}`) — they need runtime fill.
    work.update({f"interim:{i}": v for i, v in enumerate(INTERIM_ACKS)})
    work.update({f"interim_slow:{i}": v for i, v in enumerate(INTERIM_ACKS_SLOW)})

    print(f"Rendering {len(work)} voices…")
    for key, text in work.items():
        print(f"  • {key}")
        payload = await render_one(key, text)
        await cache_to_ddb(key, payload)
        print(f"    media_id={payload['media_id']}, s3={payload['s3_uri']}")

    print(f"\n✓ Cached {len(work)} system voices in DDB.")


if __name__ == "__main__":
    asyncio.run(main())
