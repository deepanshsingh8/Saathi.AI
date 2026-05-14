# Day 5 — Third flow: bill pay (concierge mode)

**Goal by EOD:** Mom says *"बिजली का बिल भर दो"* → Saathi fetches the outstanding amount from JVVNL → confirms with Mom in voice → on her approval, pings Deep on Telegram with a payment link → Deep pays from his phone → Saathi voice-confirms to Mom and forwards the receipt image.

**Out of scope today:** Polish (Day 6). Real-time autonomous BBPS payment (v2). Mobile recharge automation beyond concierge (v2).

## Why concierge mode is correct for v1

Per PLAN §3.6: real autonomous bill pay requires either BBPS integration (weeks of RBI-driven onboarding) or storing Mom's banking credentials (a hard no for v1). Concierge mode keeps the agent loop clean from Mom's POV while putting Deep in the loop for the one step that's both legally and operationally hard.

The user-facing UX is identical to a fully agentic bot. Mom doesn't know Deep paid; she sees Saathi report success. v2 swaps the "ping Deep" step for an API call and her UX doesn't change.

This is not a hack. It's the only legally clean path for a single dev in week 1.

## Prereqs from Day 4

- Two flows (medicine + grocery) working end-to-end.
- Telegram bot from Day 1 confirmed reachable.
- Deep has the JVVNL portal URL and Mom's consumer number in DDB profile.
- Mobile recharge details (operator, circle, usual amount) in DDB.

## New dependencies

```
python-telegram-bot==21.5
```

Or `httpx`-only if you prefer not to pull the SDK — the Telegram bot API is simple enough that 100 lines of httpx covers it. Decide based on whether you want polling or webhook for the "Deep confirms paid" callback.

**Recommended: httpx-only with Telegram webhook.** No polling, no SDK weight.

## Files to build

### `src/saathi/executors/bill_jvvnl.py` (new)

Playwright module for fetching the bill (not paying it):

```python
async def fetch_jvvnl_bill(consumer_number: str) -> dict:
    """Navigate to bill.jvvnl.com, enter consumer number, scrape:
    Returns:
    {
      "consumer_number": str,
      "amount_due": int,           # in paise to avoid float
      "due_date": str,              # ISO date
      "bill_number": str,
      "bill_period": str,           # e.g. "Apr 2026"
      "payment_url": str            # deep link to JVVNL's payment page or BBPS
    }
    Raises ExecutorError if portal is down or consumer number invalid.
    """
```

Notes:
- No login required for JVVNL bill view — public, just needs consumer number.
- The payment URL is what Deep clicks. JVVNL redirects to BBPS rails which accept any UPI app on Deep's phone.
- No persistent session needed. Stateless fetch.
- Cache the result for 1 hour in DDB (`pk=mom, sk=bill_cache#electricity#<bill_period>`) to avoid re-scraping if Mom asks twice.

### `src/saathi/executors/concierge.py` (extend Day 3's stub)

Full implementation:

```python
async def send_payment_request_to_deep(
    bill: dict,
    confirmation_token: str,
    mom_callback: str
) -> str:
    """Send Telegram message to Deep with:
    - Bill summary (utility, amount, due date, consumer number)
    - Payment link (deep link to JVVNL/BBPS)
    - Two inline buttons: "Mark Paid" / "Skip"
    - The confirmation_token (opaque, ties this msg to the Saathi conv)
    Returns the Telegram message_id."""

async def handle_deep_confirmation(token: str, paid: bool, receipt_image_id: str | None) -> None:
    """Called by Telegram webhook when Deep taps a button.
    Loads the pending session by token, then:
    - If paid: send Mom a voice confirmation + the receipt image.
    - If skip: send Mom a voice apology and notify Deep we'll retry later.
    """

async def notify_deep(severity: str, message: str) -> None:
    """Already exists from Day 3. Keep."""
```

### `src/saathi/app.py` (extend)

Add a new route: `POST /telegram/webhook` — receives Telegram updates when Deep taps a button or sends a message.

Verify the Telegram secret token (set via Telegram's `setWebhook` with a secret query string). Reject unknown senders (only Deep's `chat_id` is allowed).

Route based on update type:
- `callback_query` with data like `paid:<token>` or `skip:<token>` → `concierge.handle_deep_confirmation(...)`.
- `message` with photo and reply-to a Saathi payment-request message → treat as receipt upload.

### `src/saathi/llm/tools.py` (extend)

Add `BILL_TOOLS`:

```python
BILL_TOOLS = [
    {
        "name": "fetch_bill",
        "description": "Fetch outstanding bill amount for an Indian utility. Currently supports electricity (JVVNL).",
        "input_schema": {
            "type": "object",
            "properties": {
                "utility": {"type": "string", "enum": ["electricity", "mobile", "gas", "water"]},
            },
            "required": ["utility"]
        }
    },
    {
        "name": "request_payment_via_deep",
        "description": "Hand off the actual payment to Deep via Telegram. Mom doesn't see this step. Use after Mom confirms the amount.",
        "input_schema": {
            "type": "object",
            "properties": {
                "utility": {"type": "string"},
                "amount_paise": {"type": "integer"},
                "due_date": {"type": "string"},
                "consumer_number": {"type": "string"},
                "payment_url": {"type": "string"}
            },
            "required": ["utility", "amount_paise", "payment_url"]
        }
    },
    # speak_to_mom and notify_deep already exist
]
```

### `src/saathi/llm/prompts.py` (extend)

```python
BILL_SUBAGENT = SAATHI_SYSTEM + """
For this turn, you're handling a bill payment.
Profile: {profile_json}
Billers: {billers_json}

Flow:
1. Identify the utility (electricity is the default if she just said "बिल").
2. Call fetch_bill to get amount and due date.
3. Voice-summarise the amount in Hindi WORDS: e.g. "तीन हज़ार दो सौ चालीस रुपये का बिजली का बिल है, 25 तारीख तक भरना है। भर दूं?"
4. On confirm, call request_payment_via_deep with the details. This hands off to Deep.
5. Tell Mom: "ठीक है मम्मी, थोड़ी देर में confirm करती हूँ।"
6. The actual payment confirmation happens later via a separate webhook. Don't wait for it inside this turn.

Specific to bill pay:
- ALWAYS state the amount in Hindi words, digit by digit if she seems uncertain.
- ALWAYS state the due date.
- If the bill is overdue, say so explicitly: "मम्मी, last date निकल गयी है, late fees लग सकती हैं।"
- Never claim the payment is done in this turn. Saathi only confirms after Deep marks it paid.
"""
```

### Mobile recharge — concierge variant

For mobile recharge, the executor doesn't need to fetch anything — Mom just says "Jio recharge करवा दो" and Saathi knows her usual plan from DDB profile (`pk=mom, sk=profile.billers.mobile`).

Skip building a separate fetcher. Reuse `request_payment_via_deep` with a manually-constructed payment_url:
- Jio: `https://www.jio.com/selfcare/recharge?mn=<MOBILE_NUMBER>&amount=<AMOUNT>`
- Airtel: `https://www.airtel.in/recharge-online?mobile-no=<NUMBER>`

The system prompt covers both electricity and mobile recharge under the same BILL_SUBAGENT — just route on the `utility` slot from intent classification.

## Session resumption pattern

Bill pay is async by design: Saathi sends Mom a "मैं check करती हूँ" voice → does the work → Deep takes 30 seconds to pay → Saathi sends the final confirmation. This spans the 24-hour customer service window safely (entirely inside it for a quick pay), but you need to handle the case where Deep is slow:

- If Deep doesn't tap "Mark Paid" within 10 minutes, send Mom an interim: "मम्मी, थोड़ी देर और लगेगी।"
- If still no confirmation after 1 hour, escalate via `notify_deep(severity='blocked', ...)`.
- If 24-hour window closes before Deep pays, use the pre-approved `saathi_order_status` utility template to send Mom the final confirmation.

Implement the 10-minute timer with a DDB item: `pk=mom, sk=pending_bill#<token>`, with TTL. A scheduled Lambda or a simple APScheduler cron in the FastAPI process checks every minute. For v1, **APScheduler in-process** is fine — Lightsail box is always up.

## Tests

### `tests/test_executors.py` (extend)
- Mock JVVNL portal HTML; assert `fetch_jvvnl_bill` extracts amount + due date.
- Mock Telegram API; assert `send_payment_request_to_deep` posts the right message structure with inline buttons.

### Integration test
- End-to-end with Telegram in dev mode (Deep's bot, Deep's chat_id):
  1. Simulate Mom's voice "बिजली का बिल भर दो".
  2. Assert Saathi voice-summarises with the right amount.
  3. Simulate Mom's "हाँ" button.
  4. Assert Deep receives the Telegram message.
  5. Simulate Deep tapping "Mark Paid" with a fake receipt image.
  6. Assert Mom receives confirmation voice + image.

## Acceptance criteria

- [ ] Mom says *"बिजली का बिल भर दो"* → JVVNL bill fetched, voice summary with amount + due date within 30 seconds.
- [ ] Mom says *"हाँ"* → Deep gets Telegram message with payment link in under 5 seconds.
- [ ] Deep taps "Mark Paid", attaches receipt screenshot → Mom gets voice confirmation + image within 10 seconds.
- [ ] Mom says *"Jio recharge करवा दो ₹299"* → same flow, payment link is Jio's, amount is in the voice summary.
- [ ] Mom says *"रोको"* mid-flow → no Telegram message sent.
- [ ] If Deep doesn't respond in 10 min, Mom gets a "थोड़ी देर और" voice update.
- [ ] All three flows (medicine, grocery, bill) reachable from Mom's WhatsApp.

## Reality checks

1. **Test with the real JVVNL portal.** It's been known to go down for maintenance evenings. Have Saathi handle gracefully: "मम्मी, JVVNL का website अभी काम नहीं कर रहा, थोड़ी देर बाद try करूं?"
2. **Tell Mom what concierge mode is — or don't.** Decide: does Mom need to know Deep is in the loop, or do you preserve the magic? Both are valid. For a parent-child trust relationship, I'd err toward telling her ("मम्मी, payment Deep करता है, बाकी सब मैं") but defer to Deep's judgment of his Mom.
3. **Don't promise Saathi can pay mobile-recharge cards.** If Mom asks "क्या तू credit card से recharge कर सकती है?", honest answer: "अभी नहीं मम्मी, फिलहाल Deep के through हो रहा है।"

## Stop conditions

- JVVNL portal redesigned and the scraper breaks → fall back to "मम्मी, bill SMS forward कर दीजिए" workflow (parse the JVVNL SMS text with Sonnet, extract amount).
- Telegram bot rate-limited (won't happen at this scale, but if it does, fall back to email via SES).
- Deep is travelling / unreachable → concierge mode degrades to "मम्मी, अभी Deep busy है, कल हो जाएगा" — escalates but doesn't crash.

## What NOT to do today

- Do not build BBPS / Razorpay / Cashfree payment integration. v2.
- Do not store any payment instrument (card, UPI VPA, bank account). Ever in v1.
- Do not let the LLM auto-confirm payment without Deep's explicit tap. Hard guard.
- Do not auto-detect bill SMS by reading Mom's phone. v3 idea, requires Android automation.
- Do not generalize bill pay to "any biller in BBPS catalog." Two utilities for v1: electricity (JVVNL) and mobile recharge. That's it.

## EOD ritual

Update `docs/STATUS.md`. All three flows now reachable. Tomorrow is polish — not new features.

Verify in `docs/DECISIONS.md`:
- Concierge mode is documented as a v1 constraint, not a permanent design.
- BBPS path forward for v2 is named (Cashfree BBPS API or Razorpay Bharat BillPay).

Note the rough latency for each flow:
- Medicine: P50 = ?
- Grocery: P50 = ?
- Bill (to Mom's first ack): P50 = ?
- Bill (full round-trip via Deep): depends on Deep.

If any flow is >60s P50, that's a Day 6 polish target.
