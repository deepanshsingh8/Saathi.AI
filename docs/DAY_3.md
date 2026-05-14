# Day 3 — Brain + first real flow (medicine)

**Goal by EOD:** Mom says *"टेलमा 40 खत्म हो गयी, please order करवा दो"* → Saathi confirms in Hindi voice → Mom taps "हाँ" → Saathi places a COD order on 1mg or PharmEasy → Saathi confirms with order ID and ETA.

**Out of scope today:** Grocery (Day 4). Bill pay (Day 5). Polish (Day 6).

## Why medicine first

It's the most stable flow:
- Catalog doesn't change daily (unlike grocery promotions).
- SKU ambiguity is low — prescription refills name themselves.
- COD is well-supported.
- 1mg and PharmEasy both have predictable selectors with little anti-bot fight.
- If Day 3 doesn't ship a working flow, the rest of the week is at risk. Pick the easiest target.

## Prereqs from Day 2

- Voice round-trip working.
- AWS Bedrock access for Sonnet 4.6 and Haiku 4.5 confirmed in `ap-south-1`.
- Mom's profile and prescription seeded in DynamoDB (run `scripts/seed_profile.py` if not).

## New dependencies

Add to `pyproject.toml`:
```
claude-agent-sdk>=0.1.0
anthropic[bedrock]>=0.40.0
playwright==1.49.0
browserbase==1.2.0
```

Then: `uv run playwright install chromium`.

## Files to build

### `src/saathi/storage/dynamo.py` (new)

Single-table client. Methods:

```python
async def get_profile(user: str = "mom") -> dict:
    """Returns the profile item (pk=user, sk='profile')."""

async def upsert_session(user: str, conv_id: str, state: dict) -> None:
    """pk=user, sk=f'session#{conv_id}', 24h TTL."""

async def get_session(user: str, conv_id: str) -> dict | None:
    """Returns the session item or None."""

async def write_order(user: str, order: dict) -> None:
    """pk=user, sk=f'order#{ts}', persisted forever."""

async def list_medicines(user: str) -> list[dict]:
    """Query pk=user AND sk begins_with 'med#'."""
```

Use `aioboto3`. Don't introduce a heavier ORM (no pynamodb, no boto3-stubs-lite drama).

### `src/saathi/llm/intent.py` (new)

Haiku 4.5 classifier:

```python
async def classify(transcript: str) -> dict:
    """Returns:
    {
      "intent": "medicine" | "grocery" | "bill" | "chitchat" | "unknown",
      "confidence": 0.0..1.0,
      "slots": { ... extracted entities ... }
    }
    """
```

System prompt (Hindi-aware, JSON-only response):
```
You classify voice transcripts from a Hindi/Hinglish-speaking user.
She uses Saathi (a WhatsApp assistant) to order medicines, groceries, and pay utility bills.
Output ONLY a JSON object. No prose, no markdown.

Intents:
- medicine: she wants to reorder a medicine
- grocery: she wants groceries or household items
- bill: she wants to pay electricity, mobile, gas, or water
- chitchat: greetings, questions, anything not actionable
- unknown: too ambiguous

For medicine intent, also extract:
  slots.medicine_name (string, Devanagari or English as spoken)
  slots.quantity_hint (int or null)

For grocery intent:
  slots.items (list of strings) — empty list if she said "रोज़ का सामान" (usual basket)

For bill intent:
  slots.utility ("electricity"|"mobile"|"gas"|"water"|"unknown")

Examples:
"टेलमा 40 खत्म हो गयी" → {"intent":"medicine","confidence":0.95,"slots":{"medicine_name":"Telma 40","quantity_hint":null}}
"दूध ब्रेड मंगा दो" → {"intent":"grocery","confidence":0.92,"slots":{"items":["दूध","ब्रेड"]}}
"बिजली का बिल भर दो" → {"intent":"bill","confidence":0.94,"slots":{"utility":"electricity"}}
"कैसी हो?" → {"intent":"chitchat","confidence":0.99,"slots":{}}
```

Use Bedrock client directly (lighter than Agent SDK for one-shot classification). Pass `max_tokens=200`, `temperature=0`. Parse the JSON; if parse fails, return `{"intent":"unknown","confidence":0,"slots":{}}` and log.

### `src/saathi/llm/prompts.py` (new)

Pure constants. The Saathi orchestrator system prompt (Hindi-aware, COD-only, confirmation rules):

```python
SAATHI_SYSTEM = """You are Saathi (साथी), a WhatsApp assistant for Mom in Jaipur.
She speaks Hindi mixed with English. Reply in the same register.

Rules:
- Payment is always Cash on Delivery (COD). Never offer card/UPI/wallet.
- For any spend ≥ ₹100, always confirm with Mom in voice with the amount stated in Hindi words (e.g. "तीन सौ चालीस रुपये") and wait for explicit yes/no via reply button.
- For prescription medicines, use Mom's saved prescription from S3. Never substitute a different brand without asking.
- For grocery, default to Mom's "usual basket" if she says "रोज़ का" or similar.
- If you're <80% sure of intent or item, ask one clarifying question. Don't guess.
- If the executor fails twice, call notify_deep with severity='blocked' and tell Mom to wait.
- "रोको"/"cancel"/"रद्द" mid-flow = abort immediately. Don't place the order.
- Refer to yourself as Saathi, not as an AI or assistant.
- Never read out long order IDs verbatim in voice; say "ऑर्डर ID भेज दिया हूँ message में" instead.

Tools available: see allowed_tools per subagent.
"""

MEDICINE_SUBAGENT = SAATHI_SYSTEM + """
For this turn, you're handling a medicine reorder.
Profile: {profile_json}
Recent medicines: {medicines_json}

Flow:
1. Identify which medicine she means (match against recent list; if no match, ask).
2. Call search_medicine with the canonical name.
3. Present the match + price + COD ETA to Mom in voice.
4. If she confirms, call place_medicine_order with the SKU and prescription URL from profile.
5. Voice-confirm the order ID + ETA.
"""
```

Keep these as Python strings, not Jinja templates. Day 3 doesn't need a template engine.

### `src/saathi/llm/tools.py` (new)

Tool schemas for the Sonnet agent loop. Day 3 only needs medicine tools:

```python
MEDICINE_TOOLS = [
    {
        "name": "search_medicine",
        "description": "Search 1mg/PharmEasy for a medicine by name. Returns top 3 SKUs with brand, dose, MRP, COD availability.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Medicine name, e.g. 'Telma 40' or 'टेलमा 40'"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "place_medicine_order",
        "description": "Place a COD order for a specific SKU. Returns order_id and ETA. Uses Mom's saved address and prescription.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sku": {"type": "string"},
                "quantity": {"type": "integer", "minimum": 1, "maximum": 3},
                "prescription_s3_uri": {"type": "string"}
            },
            "required": ["sku", "quantity", "prescription_s3_uri"]
        }
    },
    {
        "name": "speak_to_mom",
        "description": "Send a Hindi voice message to Mom. Use for confirmations and updates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Hindi text. Will be passed through pronunciation overrides and TTS."},
                "buttons": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 20},
                    "description": "Optional 2-3 reply buttons, e.g. ['हाँ', 'नहीं']",
                    "maxItems": 3
                }
            },
            "required": ["text"]
        }
    },
    {
        "name": "notify_deep",
        "description": "Escalate to Deep via Telegram. Use only when blocked or confidence < 0.8.",
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {"type": "string", "enum": ["info", "warning", "blocked"]},
                "message": {"type": "string"}
            },
            "required": ["severity", "message"]
        }
    }
]
```

### `src/saathi/llm/orchestrator.py` (new)

The main agent loop:

```python
async def run_turn(transcript: str, conv_id: str) -> None:
    """Single conversation turn.
    1. Classify intent with Haiku.
    2. Load profile + relevant context from DDB.
    3. Pick the subagent system prompt based on intent.
    4. Run Sonnet agent loop with allowed_tools for that intent.
    5. Persist session state + any new order.
    """
```

Use `claude_agent_sdk.query()` with:
- `model="claude-sonnet-4-6"` (via Bedrock — set `CLAUDE_CODE_USE_BEDROCK=1` env or pass `provider="bedrock"`)
- `system_prompt` from `prompts.py`
- `allowed_tools` filtered to the current intent's toolset
- `max_turns=12` (plenty for one order; raise the alarm if hit)
- Tool implementations passed as Python callables that wrap your executors

Critical: load Mom's profile **once at the top** of the turn and inject as a prompt cache block (`cache_control={"type":"ephemeral"}`). 90% input-token discount on repeat turns.

### `src/saathi/executors/medicine_1mg.py` (new)

Playwright module. Functions exposed as the LLM tools above:

```python
async def search_medicine(query: str) -> list[dict]:
    """Run Playwright against 1mg.com search.
    Returns up to 3 results: [{sku, brand, dose, mrp, eta_hours, cod_available}].
    Uses persistent storage_state from Secrets Manager.
    """

async def place_medicine_order(sku: str, quantity: int, prescription_s3_uri: str) -> dict:
    """Add SKU to cart → upload prescription image from S3 → confirm address →
    select COD → place order. Returns {order_id, eta, total}.
    Raises ExecutorError on any step failure.
    """
```

Implementation notes:
- Browserbase session with `keepAlive=False`, `proxies=False` (Day 3 plan; turn on Advanced Stealth in Day 6 if needed).
- Stored login: read `storage_state_1mg.json` from Secrets Manager at start of each call; if expired (detected by redirect to login), raise `ExecutorError("session_expired")` — orchestrator escalates to Deep.
- Selectors: avoid brittle nth-child. Use accessible names where possible (`get_by_role('button', name='Add to cart')`).
- For prescription upload: download from S3 to a temp file, use Playwright's `set_input_files` on the prescription input.
- Always read the **actual cart total from the page** and return it as `total`. Never let the LLM invent the number.

### `scripts/manual_login_1mg.py` (new)

A non-headless Playwright script Deep runs **once** on his laptop:
1. Opens 1mg.com in a real Chrome.
2. Mom types her phone, gets OTP on her phone, enters it.
3. Once logged in, the script saves `context.storage_state(path='storage_state_1mg.json')`.
4. Deep uploads that JSON to AWS Secrets Manager as `saathi/1mg/storage_state`.

Re-run roughly every 30 days when cookies age out.

Same pattern for `scripts/manual_login_pharmeasy.py` (build as backup).

### `src/saathi/executors/concierge.py` (new — minimal today)

Just `notify_deep`:

```python
async def notify_deep(severity: str, message: str) -> None:
    """Send a Telegram message to Deep's chat_id with severity prefix."""
```

Full concierge mode (bill-pay handoff) is Day 5. Today just the notify side.

### `src/saathi/app.py` (extend)

Replace Day 2's echo with: voice → STT → `orchestrator.run_turn(transcript, conv_id)`.

`conv_id` derivation: hash of `(mom_number, current_24h_window_start)`. A new conv_id every time the 24h customer service window resets — matches WhatsApp's billing model and gives natural session boundaries.

Also handle inbound **button replies** (`type: interactive`, `interactive.button_reply.id`). The agent loop will have asked for confirmation by sending a message with reply buttons whose IDs are `confirm:<some_token>` / `cancel:<token>` — when the reply comes in, resume the agent loop with the user's choice.

### Button-confirmation pattern

This is the one tricky bit. The agent loop can't "wait" for Mom's button tap inside a single FastAPI request — that would block for minutes. Pattern:

1. Agent calls `speak_to_mom(text=..., buttons=["हाँ","नहीं"])`.
2. That tool sends the voice + buttons via WhatsApp, **persists the pending agent state to DDB** under `session#{conv_id}`, and returns from the agent loop with a sentinel value.
3. Webhook returns 200 to Meta. Loop ends.
4. Mom taps "हाँ". New webhook fires.
5. `app.py` detects an interactive reply, loads pending session, resumes the agent loop with the user's choice as the next "user message" in the conversation history.

The Claude Agent SDK supports this via conversation history threading — pass the prior `messages` array on resume.

For Day 3, persist just enough to resume: the pending tool call (`place_medicine_order` with its args) and a `confirmed: bool` flag. Don't try to serialize the entire SDK state; reconstruct from the transcript.

## Tests

### `tests/test_llm.py`
- `classify("टेलमा 40 खत्म हो गयी")` → `intent == "medicine"`, confidence > 0.8.
- `classify("कैसी हो")` → `intent == "chitchat"`.
- `classify("xyzabc")` → `intent == "unknown"` or low confidence.

(These hit real Bedrock; mark as `@pytest.mark.integration` and gate on env var so CI doesn't run them.)

### `tests/test_executors.py`
- Mock Playwright with a local HTML fixture that mimics 1mg's search results page; assert `search_medicine` parses the right SKUs.
- Don't run real Playwright in CI. The real flow is exercised by `scripts/smoke_test.py`.

### `scripts/smoke_test.py` (new)
Runs a real end-to-end test against Saathi's deployed instance:
1. Sends a recorded `mom_medicine.oga` voice note via WhatsApp Cloud API (using Deep's dev number, not Mom's).
2. Waits for the voice reply.
3. Logs the round-trip.
Doesn't actually place a real order — uses a `--dry-run` flag that makes the executor skip the final "place order" click.

## Acceptance criteria

- [ ] Mom says *"टेलमा 40 खत्म हो गयी, please order करवा दो"* → within 30 seconds gets a voice reply summarizing the order + 2 buttons.
- [ ] Mom taps "हाँ" → order placed on 1mg → within 60 seconds, voice confirmation with order ID.
- [ ] Mom taps "नहीं" → order cancelled, voice acknowledgment.
- [ ] Mom says *"रोको"* in a follow-up voice note mid-flow → agent aborts cleanly.
- [ ] Unknown intent ("मौसम कैसा है") → polite Hindi deflection ("मम्मी, मैं सिर्फ सामान और दवा order कर सकती हूँ").
- [ ] Order persists in DDB under `pk=mom, sk=order#<ts>`.
- [ ] `uv run pytest -q -m "not integration"` is green.

## Reality checks

1. **Sit with Mom and do one real order.** Real prescription, real address, real COD. Mom's reaction is the truth.
2. **Check the order actually arrives.** It's not done until the delivery rider hands her the bag.
3. **Time the round-trip.** P50 should be under 30s for the initial reply, under 60s for the post-confirmation order placement. If it's worse, investigate (probably Playwright on Browserbase cold start).

## Stop conditions

- 1mg cookie expired and Mom isn't reachable for OTP → switch to PharmEasy backup or notify Deep.
- 1mg out of stock for the SKU → present alternative or escalate.
- LLM hallucinates a SKU not returned by search → enforce in code: refuse `place_medicine_order` if `sku` not in last `search_medicine` results. This is a hard guard, not a prompt instruction.
- Sonnet enters a tool-call loop (calls `search_medicine` 5+ times) → max_turns=12 caps it, then notify_deep.
- Browserbase free tier exhausted (1 browser hour/month) → upgrade to Developer plan ($20). Likely on Day 3 itself.

## What NOT to do today

- Do not build the grocery executor. Day 4.
- Do not build the bill-fetch flow. Day 5.
- Do not refactor `whatsapp.py` to add Swiggy/Blinkit SDK clients.
- Do not enable Swiggy MCP integration even if the whitelist comes through today. That's Day 4 — keep today focused.
- Do not introduce a vector DB or RAG for Mom's medicine list. A dict in DDB is the entire data model.
- Do not skip the button-confirmation pattern by auto-placing orders. Every order ≥ ₹100 needs explicit confirmation.

## EOD ritual

Update `docs/STATUS.md` with Day 3 section. Decide tomorrow's path:
- If Swiggy MCP whitelist arrived → Day 4 uses Swiggy Instamart MCP path.
- If not → Day 4 uses Playwright on Blinkit (same pattern as today on 1mg).

Add to `docs/DECISIONS.md` any choices that deviated from PLAN.md (e.g. "Used PharmEasy instead of 1mg because merchant API didn't come through; reasoning: same Playwright pattern, no functional difference for v1").
