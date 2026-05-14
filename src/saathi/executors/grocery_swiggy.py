"""Swiggy Instamart MCP executor — used only when SWIGGY_MCP_URL is set.

# STUB: This module is the Path A grocery executor. It activates only when the
# Swiggy MCP whitelist arrives and `SWIGGY_MCP_URL` / `SWIGGY_CLIENT_ID` are set
# in the env. Until then, `grocery_blinkit.py` (Path B) is the default.

The real implementation will use the OAuth 2.1 + PKCE flow against
``mcp.swiggy.com/im`` and dispatch to a small (≤7-tool) filtered subset of
Instamart MCP tools per PLAN §3.3 — loading all 35 tools degrades Sonnet's
selection.
"""
from __future__ import annotations

from typing import Any

from saathi.config import Settings, get_settings
from saathi.executors.medicine_1mg import ExecutorError
from saathi.utils.logging import get_logger

log = get_logger(__name__)


def is_enabled(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return bool(s.SWIGGY_MCP_URL and s.SWIGGY_CLIENT_ID and s.SWIGGY_CLIENT_SECRET)


async def get_mcp_token(*, settings: Settings | None = None) -> str:
    raise ExecutorError("swiggy_auth_required")  # implementation lands when whitelist arrives


async def search_instamart(query: str, lat: float, lng: float,
                           *, settings: Settings | None = None) -> list[dict[str, Any]]:
    raise NotImplementedError("Swiggy MCP not yet wired")


async def get_or_build_cart(items: list[str], *, settings: Settings | None = None) -> dict[str, Any]:
    raise NotImplementedError("Swiggy MCP not yet wired")


async def place_instamart_order(cart_id: str, address_id: str,
                                *, settings: Settings | None = None) -> dict[str, Any]:
    raise NotImplementedError("Swiggy MCP not yet wired")
