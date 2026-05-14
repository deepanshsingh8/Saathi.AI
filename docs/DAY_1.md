# Day 1 — Accounts, plumbing, and the echo bot

**Goal by EOD:** Mom can send a WhatsApp text "hello" to Saathi's number and receive `नमस्ते मम्मी, मैं Saathi बोल रही हूँ` back. All long-lead-time access requests are filed. All infra accounts exist.

**Out of scope today:** Voice handling (Day 2). LLM routing (Day 3). Any executor (Days 3–5). Pretty replies.

## Human steps Deep must do himself (cannot delegate to Claude Code)

These block everything. Do these *first*, in this order. Some have queue waits, so file them and walk away.

### Block A: SIM and phone (60 min, physical)
- [ ] Walk to a Jio/Airtel store. Buy a prepaid SIM in Deep's name. ₹239.
- [ ] Activate it in a spare handset or as eSIM on a secondary line.
- [ ] **Do not install WhatsApp on this number.** Cloud API won't register a number that's already on consumer WhatsApp.

### Block B: Long-lead access requests (30 min, async)

File all three in parallel; they have multi-day wait times:

- [ ] **Swiggy MCP whitelist** — open an issue on `github.com/Swiggy/swiggy-mcp-server-manifest` with label `mcp client request`. Include: use case ("personal commerce assistant for family"), callback URL (`https://saathi.<your-domain>/oauth/swiggy/callback`), expected volume (10 orders/week).
- [ ] **Tata 1mg merchant API** — email via the form at `onedoc.1mg.com` (or `merchant-support@1mg.com` if reachable). Request merchant API access for personal health assistant pilot. Attach PAN.
- [ ] **Razorpay agentic UPI waitlist** — sign up at `razorpay.com/agentic-payments`. Won't help this week but you want a place in the queue.

### Block C: Meta WhatsApp setup (45 min, online)
- [ ] Sign up at `developers.facebook.com`.
- [ ] Create app: type "Business", use case "Other".
- [ ] Add "WhatsApp" product. Note the Phone Number ID and WABA ID from the API Setup panel.
- [ ] Register Saathi's SIM number in API Setup → "Add phone number" → verify OTP.
- [ ] Add Mom's number under "To" recipients (test recipient list, free until you need >5 test numbers).
- [ ] Generate a **System User token** (not the 24-hour temporary token). Permanent, scoped to `whatsapp_business_messaging` and `whatsapp_business_management`.
- [ ] **Submit utility template for review** — name `saathi_order_status`, category `UTILITY`, language `hi`. Body:
  ```
  नमस्ते {{1}}, आपका {{2}} ऑर्डर {{3}} है। समय: {{4}}।
  अगर कुछ बदलना है, एक voice note भेजिए।
  ```
  Submit a second template `saathi_order_status_v2` with slightly different wording as a hedge.

### Block D: Other accounts (45 min, online)
- [ ] **Anthropic Console**: console.anthropic.com → fund $20 → grab API key. (Backup; primary path is Bedrock.)
- [ ] **AWS Bedrock**: in `ap-south-1`, request model access for `anthropic.claude-sonnet-4-6` and `anthropic.claude-haiku-4-5`. Usually instant for established accounts.
- [ ] **Sarvam AI**: sarvam.ai → signup → claim ₹1,000 free credit → API key. Try a Hindi voice clip in their Saaras v3 playground to confirm it works for your accent.
- [ ] **Browserbase**: browserbase.com → free tier signup → save API key + project ID.
- [ ] **Telegram bot** for concierge alerts: BotFather → `/newbot` → save token, save Deep's own chat_id (DM the bot then visit `api.telegram.org/bot<TOKEN>/getUpdates`).

### Block E: Mom's data (30 min, family)
- [ ] Get her recorded voice consent: ask her in person, record a 15-second voice note where she says "हाँ, Deep मेरे लिए दवा, सामान और बिल का काम करवा सकता है, Saathi भी." Save to `~/saathi-private/consent.oga`.
- [ ] Collect:
  - Full delivery address + PIN code
  - 8–10 usual grocery items (off her last Blinkit/BigBasket order)
  - 5–8 regular medicines (brand, dose, frequency) — photograph the strips
  - JVVNL electricity consumer number (off the last bill)
  - Mobile recharge: operator (Jio/Airtel), circle (Rajasthan), usual plan amount
  - One recent prescription image (photograph clearly)

## What Claude Code does today

The repo scaffold below is already created. Today's Claude Code work is small and focused: get the FastAPI app deployed, get the WhatsApp webhook handshake working, get one text round-trip from mom's number through the bot and back.

### Task 1 — Initialize the Python project

**Files to create/edit:**
- `pyproject.toml` (uv-managed, Python 3.12)
- `.gitignore`
- `.env.example`
- `README.md` (one paragraph)

**Dependencies (locked at these versions; no others today):**
```
fastapi==0.115.0
uvicorn[standard]==0.32.0
httpx==0.27.2
boto3==1.35.0
aioboto3==13.2.0
python-dotenv==1.0.1
pydantic==2.9.0
pydantic-settings==2.5.0
```

Dev:
```
pytest==8.3.0
pytest-asyncio==0.24.0
ruff==0.6.0
respx==0.21.0
```

Ruff config inline in `pyproject.toml`: line length 100, target 3.12, enable `E, F, I, W, UP, B, ASYNC`.

### Task 2 — Config

**File:** `src/saathi/config.py`

Pydantic `BaseSettings` reading from env. Required fields:
- `WA_VERIFY_TOKEN` — webhook verification string (you make this up, configure same string in Meta dashboard)
- `WA_APP_SECRET` — Meta app secret, for signature verification
- `WA_ACCESS_TOKEN` — System User token
- `WA_PHONE_ID` — Phone Number ID from API Setup
- `WA_MOM_NUMBER` — Mom's E.164 number (e.g. `+9198XXXXXXXX`), the only allowed sender
- `AWS_REGION` — default `ap-south-1`
- `DDB_TABLE` — default `saathi`
- `S3_BUCKET` — default `saathi-media`
- `LOG_LEVEL` — default `INFO`

Don't include Sarvam, Anthropic, Browserbase, Telegram secrets yet — those come on Days 2, 3, 4. Add fields as needed; don't pre-populate empty ones.

### Task 3 — Webhook skeleton

**File:** `src/saathi/app.py`

FastAPI app with two routes:

1. `GET /webhook` — Meta verification handshake.
   - Read query params `hub.mode`, `hub.verify_token`, `hub.challenge`.
   - If token matches `settings.WA_VERIFY_TOKEN`, return `int(hub_challenge)` as plain int.
   - Else return 403.

2. `POST /webhook` — Inbound messages.
   - Read raw body bytes (needed for HMAC).
   - Verify `X-Hub-Signature-256` header against `sha256=` + HMAC-SHA256(body, app_secret). Use `hmac.compare_digest`. Return 401 on mismatch.
   - Parse JSON. Locate the message under `entry[0].changes[0].value.messages[0]` (defensive — Meta also sends `statuses` updates with no `messages` key; ignore those, return 200).
   - Drop silently (200) if sender (`from` field) ≠ `settings.WA_MOM_NUMBER`. Log a warning.
   - For today only: if message type is `text`, call a stub `handle_text_message(msg)` that does the echo. Other types: log and ignore.

Also add `GET /healthz` returning `{"ok": true, "service": "saathi"}` for Lightsail health checks.

### Task 4 — WhatsApp client (send only, for now)

**File:** `src/saathi/messaging/whatsapp.py`

One function for today:

```python
async def send_text(to: str, body: str) -> str:
    """POST to graph.facebook.com/v22.0/{phone_id}/messages.
    Returns the WAMID (message ID) on success, raises WhatsAppError on failure.
    Logs the structured request/response (without the access token).
    """
```

Use `httpx.AsyncClient` with a 10s timeout. Auth header: `Bearer {WA_ACCESS_TOKEN}`. Payload:
```json
{"messaging_product": "whatsapp", "to": "+91...", "type": "text", "text": {"body": "..."}}
```

Define `WhatsAppError` in the same module.

### Task 5 — Wire the echo

In `app.py`'s `handle_text_message`, call `send_text(msg["from"], "नमस्ते मम्मी, मैं Saathi बोल रही हूँ")`.

That's it for Day 1's bot logic. No LLM, no speech, no DB writes.

### Task 6 — Tests

**File:** `tests/test_messaging.py`

- Test webhook signature verification: known body + known secret → known signature, assert match. Mismatch → assert fail.
- Test webhook routing: payload from `WA_MOM_NUMBER` → handler called; payload from another number → handler NOT called, returns 200.
- Test `send_text` with `respx` mocking `graph.facebook.com`: assert correct Bearer header, correct payload, returns WAMID on 200, raises `WhatsAppError` on 400.

Run with `uv run pytest -q`. All green before EOD.

### Task 7 — Deploy to Lightsail

**File:** `scripts/deploy.sh` (optional convenience)

Manual steps Deep does (Claude Code can write the script, Deep runs it):

1. SSH to Lightsail instance.
2. `git clone` the repo.
3. `uv sync` to install deps.
4. Set up systemd unit `saathi.service` to run `uvicorn saathi.app:app --host 127.0.0.1 --port 8000`.
5. Caddy config: `saathi.<your-domain> { reverse_proxy 127.0.0.1:8000 }`. Caddy handles HTTPS.
6. Point DNS A record at the Lightsail static IP.

Verify `https://saathi.<your-domain>/healthz` returns 200.

### Task 8 — Connect webhook to Meta

Deep (in Meta dashboard): WhatsApp → Configuration → Webhook → Callback URL `https://saathi.<your-domain>/webhook`, Verify Token = the value in your `.env`. Subscribe to `messages` and `message_template_status_update`.

Click "Verify and save". Meta will hit `GET /webhook` and your route returns the challenge. If it works, the dashboard shows green.

## Acceptance criteria — must be true at EOD

- [ ] `https://saathi.<domain>/healthz` returns 200 over HTTPS.
- [ ] Meta webhook configuration shows verified/green.
- [ ] Deep sends `hello` from Mom's number → Mom receives `नमस्ते मम्मी, मैं Saathi बोल रही हूँ` within 5 seconds.
- [ ] Deep sends `hello` from any other number → no reply (silently dropped, logged).
- [ ] `uv run pytest -q` is all green.
- [ ] `docs/STATUS.md` updated with what's running, what's pending (Swiggy whitelist, 1mg API, WhatsApp template review).
- [ ] All Block A–E human steps complete or queued (whitelist requests filed even if not yet approved).

## Stop conditions — when to ask Deep

- Meta refuses to register Saathi's SIM (sometimes happens with brand-new prepaid numbers; takes 24h to settle).
- Webhook verification fails repeatedly after correct token (often a Lightsail firewall thing — port 443 must be open).
- Mom's number rejects messages with error `131047` (re-engagement window) — won't happen on first contact but flag if it does.
- Bedrock model access request is denied (rare; usually instant approval).

## What NOT to do today

- Do not start writing the Sarvam wrapper. Day 2.
- Do not start writing the orchestrator/LLM code. Day 3.
- Do not pre-build executor modules. Days 3–5.
- Do not "while I'm here" refactor anything in the scaffold. The scaffold is intentional.
- Do not add any dependency not in the Task 1 list.
- Do not commit any secrets. `.env` is gitignored. `.env.example` has placeholder values only.

## EOD ritual

Update `docs/STATUS.md`:

```markdown
## Day 1 — done <date>

### Running
- Lightsail Mumbai instance, FastAPI behind Caddy on saathi.<domain>
- Webhook receives and echoes from Mom's number

### Built
- src/saathi/config.py — env settings
- src/saathi/app.py — webhook routes
- src/saathi/messaging/whatsapp.py — send_text
- tests/test_messaging.py — 6 tests passing

### Stubbed
- (none yet)

### Pending external
- Swiggy MCP whitelist (filed)
- 1mg merchant API (emailed)
- WhatsApp template saathi_order_status (in review, expect Day 2-3)

### Next
- Day 2: Sarvam STT/TTS, voice round-trip
```

If you got here, the hard part is done. Day 2 is fun.
