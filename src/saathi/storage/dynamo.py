"""DynamoDB single-table client.

Table: ``saathi`` (ap-south-1), ``pk`` + ``sk`` string keys, on-demand,
TTL attribute ``ttl``.

Layout (per PLAN §5.5):
    pk       sk                       attributes
    mom      profile                  {address, pin, billers, meds, prescriptions}
    mom      session#<conv_id>        {last_intent, slots, opened_at, expires_at, aborted}
    mom      order#<ts>               {source, items, amount, status, eta, cod}
    mom      med#<sku>                {brand, dose, frequency_days, last_ordered}
    mom      prescription#<ts>        {s3_url, doctor, expiry, items}
    mom      basket#default           {items: [{name, search_query, quantity}]}
    mom      bill_cache#<utility>#<period>  {amount_paise, due_date, ...}
    mom      pending_bill#<token>     {bill, mom_callback, created_at}     (TTL: 1h)
"""
from __future__ import annotations

import time
from typing import Any

import aioboto3
from boto3.dynamodb.conditions import Key

from saathi.config import get_settings
from saathi.utils.logging import get_logger

log = get_logger(__name__)

_session: aioboto3.Session | None = None
SESSION_TTL_SECONDS = 24 * 60 * 60  # 24h
PENDING_BILL_TTL_SECONDS = 60 * 60  # 1h


def get_session() -> aioboto3.Session:
    global _session
    if _session is None:
        _session = aioboto3.Session(region_name=get_settings().AWS_REGION)
    return _session


async def _table():
    """Async-context resource. Use as ``async with _table() as t: ...`` is wrong;
    the resource itself is the context. Pattern: ``async with get_session().resource(...)``.
    """
    s = get_settings()
    return get_session().resource("dynamodb", region_name=s.AWS_REGION)


# ─── Profile ─────────────────────────────────────────────────────────────────


async def get_profile(user: str = "mom") -> dict[str, Any]:
    s = get_settings()
    async with get_session().resource("dynamodb", region_name=s.AWS_REGION) as ddb:
        table = await ddb.Table(s.DDB_TABLE)
        resp = await table.get_item(Key={"pk": user, "sk": "profile"})
        return resp.get("Item", {})


async def put_profile(profile: dict[str, Any], user: str = "mom") -> None:
    s = get_settings()
    item = {**profile, "pk": user, "sk": "profile"}
    async with get_session().resource("dynamodb", region_name=s.AWS_REGION) as ddb:
        table = await ddb.Table(s.DDB_TABLE)
        await table.put_item(Item=item)
    log.info("ddb_profile_put", user=user)


# ─── Session (24h TTL) ───────────────────────────────────────────────────────


async def upsert_session(user: str, conv_id: str, state: dict[str, Any]) -> None:
    s = get_settings()
    now = int(time.time())
    item = {
        **state,
        "pk": user,
        "sk": f"session#{conv_id}",
        "updated_at": now,
        "ttl": now + SESSION_TTL_SECONDS,
    }
    async with get_session().resource("dynamodb", region_name=s.AWS_REGION) as ddb:
        table = await ddb.Table(s.DDB_TABLE)
        await table.put_item(Item=item)


async def get_session_state(user: str, conv_id: str) -> dict[str, Any] | None:
    s = get_settings()
    async with get_session().resource("dynamodb", region_name=s.AWS_REGION) as ddb:
        table = await ddb.Table(s.DDB_TABLE)
        resp = await table.get_item(Key={"pk": user, "sk": f"session#{conv_id}"})
        return resp.get("Item")


async def set_abort_flag(user: str, conv_id: str, value: bool = True) -> None:
    """Day 6 polish 3: server-side abort flag checked by every tool call."""
    s = get_settings()
    async with get_session().resource("dynamodb", region_name=s.AWS_REGION) as ddb:
        table = await ddb.Table(s.DDB_TABLE)
        await table.update_item(
            Key={"pk": user, "sk": f"session#{conv_id}"},
            UpdateExpression="SET aborted = :v, updated_at = :t",
            ExpressionAttributeValues={":v": value, ":t": int(time.time())},
        )


# ─── Orders ──────────────────────────────────────────────────────────────────


async def write_order(user: str, order: dict[str, Any]) -> str:
    s = get_settings()
    ts = int(time.time() * 1000)
    sk = f"order#{ts}"
    item = {**order, "pk": user, "sk": sk, "created_at": ts}
    async with get_session().resource("dynamodb", region_name=s.AWS_REGION) as ddb:
        table = await ddb.Table(s.DDB_TABLE)
        await table.put_item(Item=item)
    log.info("ddb_order_written", sk=sk, source=order.get("source"))
    return sk


# ─── Medicines ───────────────────────────────────────────────────────────────


async def list_medicines(user: str = "mom") -> list[dict[str, Any]]:
    s = get_settings()
    async with get_session().resource("dynamodb", region_name=s.AWS_REGION) as ddb:
        table = await ddb.Table(s.DDB_TABLE)
        resp = await table.query(
            KeyConditionExpression=Key("pk").eq(user) & Key("sk").begins_with("med#"),
        )
        return resp.get("Items", [])


# ─── Usual basket ────────────────────────────────────────────────────────────


async def get_usual_basket(user: str = "mom") -> dict[str, Any]:
    s = get_settings()
    async with get_session().resource("dynamodb", region_name=s.AWS_REGION) as ddb:
        table = await ddb.Table(s.DDB_TABLE)
        resp = await table.get_item(Key={"pk": user, "sk": "basket#default"})
        return resp.get("Item", {})


async def put_usual_basket(items: list[dict[str, Any]], user: str = "mom") -> None:
    s = get_settings()
    async with get_session().resource("dynamodb", region_name=s.AWS_REGION) as ddb:
        table = await ddb.Table(s.DDB_TABLE)
        await table.put_item(Item={"pk": user, "sk": "basket#default", "items": items})


# ─── Bill cache (1h) and pending-bill (1h TTL for concierge handoff) ─────────


async def get_bill_cache(user: str, utility: str, period: str) -> dict[str, Any] | None:
    s = get_settings()
    async with get_session().resource("dynamodb", region_name=s.AWS_REGION) as ddb:
        table = await ddb.Table(s.DDB_TABLE)
        resp = await table.get_item(
            Key={"pk": user, "sk": f"bill_cache#{utility}#{period}"},
        )
        return resp.get("Item")


async def put_bill_cache(user: str, utility: str, period: str, bill: dict[str, Any]) -> None:
    s = get_settings()
    now = int(time.time())
    item = {**bill, "pk": user, "sk": f"bill_cache#{utility}#{period}", "ttl": now + 3600}
    async with get_session().resource("dynamodb", region_name=s.AWS_REGION) as ddb:
        table = await ddb.Table(s.DDB_TABLE)
        await table.put_item(Item=item)


async def put_pending_bill(token: str, payload: dict[str, Any], user: str = "mom") -> None:
    s = get_settings()
    now = int(time.time())
    item = {
        **payload,
        "pk": user,
        "sk": f"pending_bill#{token}",
        "created_at": now,
        "ttl": now + PENDING_BILL_TTL_SECONDS,
    }
    async with get_session().resource("dynamodb", region_name=s.AWS_REGION) as ddb:
        table = await ddb.Table(s.DDB_TABLE)
        await table.put_item(Item=item)


async def get_pending_bill(token: str, user: str = "mom") -> dict[str, Any] | None:
    s = get_settings()
    async with get_session().resource("dynamodb", region_name=s.AWS_REGION) as ddb:
        table = await ddb.Table(s.DDB_TABLE)
        resp = await table.get_item(Key={"pk": user, "sk": f"pending_bill#{token}"})
        return resp.get("Item")


async def delete_pending_bill(token: str, user: str = "mom") -> None:
    s = get_settings()
    async with get_session().resource("dynamodb", region_name=s.AWS_REGION) as ddb:
        table = await ddb.Table(s.DDB_TABLE)
        await table.delete_item(Key={"pk": user, "sk": f"pending_bill#{token}"})
