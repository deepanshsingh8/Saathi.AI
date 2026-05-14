# Day 4 — Second flow: groceries

**Goal by EOD:** Mom says *"दूध, ब्रेड, और अंडे मंगवा दो"* or *"रोज़ का सामान"* → Saathi confirms cart in voice → Mom approves → COD order placed on Blinkit (default) or Swiggy Instamart (if whitelisted).

**Out of scope today:** Bill pay (Day 5). Polish (Day 6). Swiggy Food/Dineout (never v1).

## Path selection — read first

Check `docs/STATUS.md` from Day 3 EOD. There are two paths:

### Path A: Swiggy Instamart MCP whitelist arrived ✅
Use `mcp.swiggy.com/im`. Cleanest implementation. OAuth flow, then tool-calling via Claude Agent SDK's native MCP support. Skip to "Path A build" below.

### Path B: Whitelist didn't arrive (default assumption)
Use Playwright on Blinkit. Same pattern as Day 3's 1mg flow. Most of Day 4 work is duplicating the Day 3 module structure for a different site. Skip to "Path B build" below.

**Don't try both today.** Pick one, ship it. The other can be a Day 6 add.

## Prereqs from Day 3

- Medicine flow working end-to-end with at least one real test order.
- Button-confirmation pattern proven.
- Browserbase Developer plan ($20/mo) — likely needed after Day 3 ate the free hour.
- Mom's "usual basket" pre-loaded in DDB under `pk=mom, sk=basket#default`.

## New dependencies

If Path A: nothing new (Claude Agent SDK handles MCP).
If Path B: nothing new (Playwright already installed Day 3).

Either way, no new pip installs.

---

## Path A build — Swiggy Instamart MCP

### `src/saathi/executors/grocery_swiggy.py` (new)

Wrap Swiggy MCP as Saathi's grocery executor. Architecture:

```python
async def get_mcp_token() -> str:
    """OAuth 2.1 + PKCE flow. Cached refresh token in Secrets Manager.
    On expiry, raise ExecutorError('swiggy_auth_required') — orchestrator
    notifies Deep to re-authorize."""

async def search_instamart(query: str, lat: float, lng: float) -> list[dict]:
    """Call swiggy_im.search tool via MCP. Returns [{sku, name, price, in_stock}]."""

async def get_or_build_cart(items: list[str]) -> dict:
    """For each item, search → take top match → add to cart.
    Returns cart summary with total."""

async def place_instamart_order(cart_id: str, address_id: str) -> dict:
    """Place COD order. Returns {order_id, eta, total}."""
```

### Orchestrator wiring

In `src/saathi/llm/orchestrator.py`, add a new subagent system prompt `GROCERY_SUBAGENT` and a new tools list `GROCERY_TOOLS_SWIGGY`. Critical: **don't load all 35 Swiggy MCP tools**. Filter to 5–7 relevant ones (`search`, `add_to_cart`, `get_cart`, `place_order`, `get_eta`).

Per PLAN §3.3 — loading all 35 tools degrades Sonnet's tool selection.

In Agent SDK config:
```python
mcp_servers={
    "swiggy_im": {
        "type": "http",
        "url": "https://mcp.swiggy.com/im",
        "headers": {"Authorization": f"Bearer {token}"}
    }
}
allowed_tools=["mcp__swiggy_im__search", "mcp__swiggy_im__add_to_cart", ...]
```

### Tests
- Mock MCP responses with `respx` — assert correct tool sequencing.
- Don't hit real MCP in unit tests.

---

## Path B build — Playwright on Blinkit

### `src/saathi/executors/grocery_blinkit.py` (new)

Same shape as `medicine_1mg.py` from Day 3. Functions:

```python
async def search_blinkit(query: str) -> list[dict]:
    """Search blinkit.com. Returns [{sku, name, price, pack_size, in_stock}]."""

async def add_to_cart(sku: str, quantity: int) -> dict:
    """Returns updated cart {items, total, eta_minutes}."""

async def get_cart() -> dict:
    """Returns current cart contents from the page."""

async def checkout_cod(address_id: str) -> dict:
    """Final checkout step with COD. Returns {order_id, eta, total}."""

async def check_pin_serviceable(pin: str) -> bool:
    """Hit Blinkit's serviceability endpoint before promising an ETA."""
```

Implementation notes:
- Persistent session via `storage_state_blinkit.json` in Secrets Manager.
- Same OTP-once-manually pattern via `scripts/manual_login_blinkit.py`.
- **Always call `check_pin_serviceable` first** before any cart operations. Some southern Jaipur PINs flake during peak hours.
- Read cart total from the page DOM, never let the LLM invent it.
- For "रोज़ का सामान" (usual basket), look up `sk='basket#default'` in DDB → loop `add_to_cart` per SKU. If an item is out of stock, skip + flag in the cart summary; Saathi reports it to Mom.

### `src/saathi/llm/tools.py` (extend)

Add `GROCERY_TOOLS` paralleling `MEDICINE_TOOLS`. Same shape: `search_grocery`, `add_grocery_to_cart`, `get_grocery_cart`, `place_grocery_order`, plus the shared `speak_to_mom` and `notify_deep`.

### `src/saathi/llm/prompts.py` (extend)

Add `GROCERY_SUBAGENT` system prompt:

```python
GROCERY_SUBAGENT = SAATHI_SYSTEM + """
For this turn, you're handling a grocery order.
Profile: {profile_json}
Usual basket: {usual_basket_json}

Flow:
1. If Mom said "रोज़ का" or "usual" — load the usual basket.
2. Otherwise, parse the items from her transcript.
3. For each item, call search_grocery and pick the top match (smallest viable pack size unless she specified).
4. Call get_grocery_cart for the total.
5. Voice-summarise: "मम्मी, आपका सामान: दूध, ब्रेड, अंडे — कुल तीन सौ चालीस रुपये, बीस मिनट में आ जाएगा। order करूं?"
6. On confirm, call place_grocery_order. On decline, voice-confirm cancellation.

Rules specific to grocery:
- Default to the smallest viable pack size. Mom prefers fresh stock over bulk.
- If any item is out of stock, mention it in the voice summary and ask if she wants a substitute or skip.
- Don't ask about substitutes for staples (milk, bread) — just use the closest brand.
- Quantity defaults to 1 unless she specified.
"""
```

### `src/saathi/llm/orchestrator.py` (extend)

Add intent routing for `grocery`:
```python
if intent.intent == "grocery":
    system_prompt = GROCERY_SUBAGENT.format(...)
    allowed_tools = ["search_grocery", "add_grocery_to_cart", ...]
```

Keep medicine path unchanged.

### `scripts/manual_login_blinkit.py` (new)

Same shape as `manual_login_1mg.py`. Non-headless Playwright, Mom does OTP once, save `storage_state` to Secrets Manager.

### `scripts/seed_usual_basket.py` (new)

Reads a JSON file Deep prepares (`scripts/data/usual_basket.json`) and writes it to DDB under `pk=mom, sk=basket#default`. Example content:
```json
{
  "items": [
    {"name": "Amul Toned Milk 1L", "search_query": "Amul toned milk 1L", "quantity": 2},
    {"name": "Britannia Brown Bread", "search_query": "Britannia brown bread", "quantity": 1},
    {"name": "Eggs (6)", "search_query": "eggs 6 pack", "quantity": 1},
    ...
  ]
}
```

Run once before testing. Mom's actual basket items come from her last 2 orders on Blinkit/BigBasket — Deep gets them from her order history.

## Tests

### `tests/test_executors.py` (extend)
- Mock Blinkit search HTML; assert `search_blinkit` parses SKU/price correctly.
- Mock PIN serviceability response; assert `check_pin_serviceable("302017")` returns True.
- Mock checkout flow; assert the final order_id is captured from the response page.

### `scripts/smoke_test.py` (extend)
Add a grocery smoke test mode (`--flow=grocery --dry-run`). Same pattern as Day 3.

## Acceptance criteria

- [ ] Mom says *"दूध, ब्रेड, अंडे मंगवा दो"* → voice reply with cart total + buttons within 45 seconds.
- [ ] Mom says *"रोज़ का सामान"* → usual basket is loaded, voice reply lists items + total.
- [ ] Mom taps "हाँ" → COD order placed on Blinkit/Instamart.
- [ ] Mom says *"दही भी डाल दो"* (additional item, mid-flow) → cart updated, total re-stated.
- [ ] Out-of-stock item → mentioned in voice summary, not silently dropped.
- [ ] Tests green; one real order actually delivered to Mom by EOD.

## Reality checks

1. **Have Mom describe her usual basket out loud.** Compare with the JSON Deep seeded — Mom often says things like "वो वाली ब्रेड" (that bread) which doesn't map cleanly. Add aliases to `usual_basket.json` if needed.
2. **Watch what happens when something's out of stock.** Out-of-stock handling is where most grocery bots fail. Mom should hear about it, not get a half-order.
3. **Check Blinkit COD reliability.** Blinkit reportedly cancels some COD orders. Order three small items, see what arrives.

## Stop conditions

- Blinkit blocks the Browserbase session (IP block, CAPTCHA wall) → switch to Zepto (same Playwright pattern, build `grocery_zepto.py` as parallel module).
- Mom's PIN shows "out of zone" during the test → manually verify on her phone; if Blinkit's app also says no, this is a coverage issue, not a code issue.
- Sonnet picks the wrong pack size repeatedly → tighten the system prompt with explicit "always smallest pack unless said otherwise" example.
- Cart total mismatch between Saathi's voice reply and the actual placed order → bug. Read the total from the cart page DOM, not from cumulative search prices.

## What NOT to do today

- Do not start the bill pay flow. Day 5.
- Do not generalize the executor base class. Premature abstraction. Each merchant gets its own module.
- Do not add a price-comparison feature (Blinkit vs Zepto vs Instamart). v3.
- Do not learn the basket from observed orders. Hand-curated for v1; learning is v2.
- Do not store Mom's payment info even if Blinkit prompts to save card. COD only.

## EOD ritual

Update `docs/STATUS.md`. Two flows working end-to-end. Note which path you took (Swiggy MCP vs Blinkit Playwright) in `docs/DECISIONS.md`.

If Day 4 ran long and grocery is half-working: ship medicine + descope grocery to "fetches cart but Deep does final confirm" mode. That's still useful for Mom. Don't ship a broken auto-order.
