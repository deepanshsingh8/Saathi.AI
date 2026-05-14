# Saathi — Build TODO (Day 1 → 7)

Source of truth for execution. Mirrors `docs/DAY_N.md` but split between **Human track** (Deep) and **Code track** (Claude Code). Mark with `[x]` as items land.

Stack and scope rules: see `CLAUDE.md`. Never silently expand scope across days.

---

## Day 1 — Accounts, plumbing, echo bot

### Human track (Deep, blocking real-world test)
- [ ] **Block A — SIM**: prepaid Jio/Airtel SIM in Deep's name, do NOT install consumer WhatsApp on it
- [ ] **Block B — long-lead requests** (file in parallel, multi-day SLAs):
  - [ ] Swiggy MCP whitelist issue on `Swiggy/swiggy-mcp-server-manifest`
  - [ ] Tata 1mg merchant API request via `onedoc.1mg.com`
  - [ ] Razorpay agentic UPI waitlist
- [ ] **Block C — Meta WhatsApp**:
  - [ ] developers.facebook.com app, WhatsApp product, register Saathi SIM
  - [ ] Add Mom's number under test recipients
  - [ ] Generate System User token (permanent), scope `whatsapp_business_messaging` + `whatsapp_business_management`
  - [ ] Submit `saathi_order_status` (Hindi UTILITY) + `saathi_order_status_v2` hedge template
- [ ] **Block D — other accounts**:
  - [ ] Anthropic Console + $20 credit
  - [ ] AWS Bedrock model access for `claude-sonnet-4-6` and `claude-haiku-4-5` in `ap-south-1`
  - [ ] Sarvam AI signup + ₹1,000 credit + Saaras v3 playground sanity check
  - [ ] Browserbase free tier signup
  - [ ] Telegram BotFather + record Deep's chat_id
- [ ] **Block E — Mom's data**:
  - [ ] Recorded voice consent → `~/saathi-private/consent.oga`
  - [ ] Address + PIN, 8–10 grocery items, 5–8 medicines (photographed), JVVNL consumer number, mobile recharge details, one prescription image
- [ ] **Deploy**: provision Lightsail Mumbai 2 GB, point `saathi.<domain>`, install Caddy + uv + Python 3.12, run `scripts/deploy.sh`
- [ ] **Wire Meta webhook**: callback URL `https://saathi.<domain>/webhook`, verify token = `WA_VERIFY_TOKEN`, subscribe to `messages` + `message_template_status_update`
- [ ] **Smoke test**: send "hello" from Mom's number → expect Hindi greeting back within 5s

### Code track (Claude Code)
- [x] `tasks/todo.md` + `tasks/lessons.md`
- [ ] `README.md` → one-paragraph project blurb
- [ ] `src/saathi/utils/logging.py` — structured JSON logger (stdout)
- [ ] `src/saathi/config.py` — pydantic-settings, Day 1 fields only
- [ ] `src/saathi/messaging/whatsapp.py` — `send_text(to, body) -> wamid` + `WhatsAppError`
- [ ] `src/saathi/app.py` — `GET/POST /webhook`, HMAC verify, mom-only filter, `GET /healthz`, `handle_text_message` echo
- [ ] `tests/test_messaging.py` — sig verify, routing, send_text via respx
- [ ] `scripts/deploy.sh` + sample `saathi.service` + `Caddyfile` snippet
- [ ] `uv sync` + `uv run pytest -q` green
- [ ] `docs/STATUS.md` updated to Day 1 done

### Acceptance (from `docs/DAY_1.md`)
- [ ] `https://saathi.<domain>/healthz` 200 over HTTPS
- [ ] Meta webhook configuration verified/green
- [ ] Mom→hello → Hindi reply ≤5s
- [ ] Other senders silently dropped
- [ ] All Day 1 tests green

---

## Day 2 — Voice in/out

### Human track
- [ ] Create S3 bucket `saathi-media` in `ap-south-1` with SSE-KMS default
- [ ] Record fixtures with Mom: `mom_hello.oga`, `mom_medicine.oga`, `mom_amount.oga`
- [ ] Listen to vidya/anushka samples → lock `TTS_VOICE`
- [ ] Pronunciation audit — note brand mispronunciations for `PRONUNCIATION_OVERRIDES`

### Code track
- [ ] `src/saathi/storage/s3.py` — `put_voice`, `get_object` (aioboto3, single shared session)
- [ ] `src/saathi/messaging/whatsapp.py` extend — `download_media`, `upload_media`, `send_audio`
- [ ] `src/saathi/speech/sarvam.py` — `transcribe`, `synthesize`, `SarvamError`
- [ ] `src/saathi/speech/fallback.py` — Whisper stub (NotImplementedError, label as STUB)
- [ ] `src/saathi/utils/hindi.py` — `rupees_to_hindi_words`, `apply_pronunciation_overrides`, `PRONUNCIATION_OVERRIDES` dict
- [ ] `src/saathi/app.py` extend — `handle_audio_message` inline pipeline (download → S3 → STT → echo TTS → send_audio)
- [ ] `tests/test_speech.py` + extend `tests/test_messaging.py`
- [ ] STATUS.md updated, P50 latency logged

### Acceptance
- [ ] Mom voice → voice echo ≤6s
- [ ] Hinglish: "Telma" preserved as English in codemix mode
- [ ] Inbound voice notes appear in `s3://saathi-media/mom/inbound/`
- [ ] All tests green

---

## Day 3 — Brain + medicine flow

### Human track
- [ ] Bedrock model access confirmed live in `ap-south-1`
- [ ] DDB table `saathi` created (PK + SK strings, on-demand, TTL attr `ttl`)
- [ ] Run `scripts/seed_profile.py` with Mom's address/billers/meds/prescription S3 URI
- [ ] Run `scripts/manual_login_1mg.py` once on Deep's laptop, upload `storage_state_1mg.json` to Secrets Manager as `saathi/1mg/storage_state`
- [ ] (Backup) Same for `manual_login_pharmeasy.py`
- [ ] Browserbase Developer plan ($20/mo) if free tier exhausted

### Code track
- [ ] `src/saathi/storage/dynamo.py` — `get_profile`, `upsert_session`, `get_session`, `write_order`, `list_medicines`
- [ ] `src/saathi/llm/intent.py` — Haiku 4.5 classifier (JSON-only, Hindi-aware)
- [ ] `src/saathi/llm/prompts.py` — `SAATHI_SYSTEM`, `MEDICINE_SUBAGENT`
- [ ] `src/saathi/llm/tools.py` — `MEDICINE_TOOLS` (search_medicine, place_medicine_order, speak_to_mom, notify_deep)
- [ ] `src/saathi/llm/orchestrator.py` — `run_turn`, prompt-cache profile block, button-confirm pattern
- [ ] `src/saathi/executors/medicine_1mg.py` — `search_medicine`, `place_medicine_order` (Browserbase + Playwright + storage_state)
- [ ] `src/saathi/executors/concierge.py` — `notify_deep` only (Telegram POST)
- [ ] `scripts/seed_profile.py`, `scripts/manual_login_1mg.py`, `scripts/manual_login_pharmeasy.py`, `scripts/smoke_test.py --flow=medicine --dry-run`
- [ ] `src/saathi/app.py` extend — replace echo with `orchestrator.run_turn`, handle interactive button replies, conv_id derivation
- [ ] Tests + STATUS update

### Acceptance
- [ ] Voice "टेलमा 40 खत्म हो गयी" → confirm voice + 2 buttons ≤30s
- [ ] "हाँ" → real COD order placed → voice confirmation with order ID ≤60s
- [ ] "नहीं" / "रोको" → clean abort
- [ ] Order persisted at `pk=mom, sk=order#<ts>`
- [ ] SKU guard: `place_medicine_order` refuses any `sku` not in last `search_medicine` results

---

## Day 4 — Grocery (path A or B)

### Decision point (EOD Day 3)
- [ ] If Swiggy MCP whitelist arrived → **Path A** (`mcp.swiggy.com/im`, OAuth 2.1 + PKCE, filter to ~7 tools)
- [ ] Else → **Path B** (Playwright on Blinkit, mirror `medicine_1mg.py` pattern)

### Human track
- [ ] Path A: Swiggy OAuth flow once for Mom, persist refresh token in Secrets Manager
- [ ] Path B: `scripts/manual_login_blinkit.py` → upload state to Secrets Manager
- [ ] `scripts/data/usual_basket.json` curated from Mom's last 2 orders → run `scripts/seed_usual_basket.py`

### Code track
- [ ] Path A: `src/saathi/executors/grocery_swiggy.py`
- [ ] Path B: `src/saathi/executors/grocery_blinkit.py` + `check_pin_serviceable`
- [ ] `src/saathi/llm/tools.py` extend — `GROCERY_TOOLS`
- [ ] `src/saathi/llm/prompts.py` extend — `GROCERY_SUBAGENT`
- [ ] `src/saathi/llm/orchestrator.py` extend — grocery intent routing
- [ ] `scripts/seed_usual_basket.py`, `scripts/manual_login_blinkit.py`
- [ ] Tests + STATUS update + DECISIONS.md entry for path chosen

### Acceptance
- [ ] "दूध, ब्रेड, अंडे" → cart voice + buttons ≤45s
- [ ] "रोज़ का सामान" loads usual basket
- [ ] Out-of-stock items announced, not silently dropped
- [ ] One real grocery order delivered to Mom EOD

---

## Day 5 — Bill pay (concierge mode)

### Human track
- [ ] Telegram bot `setWebhook` URL pointed at `https://saathi.<domain>/telegram/webhook` with secret token
- [ ] JVVNL consumer number verified in DDB profile
- [ ] Mobile recharge defaults (operator/circle/amount) seeded

### Code track
- [ ] `src/saathi/executors/bill_jvvnl.py` — `fetch_jvvnl_bill` (no login, public consumer-number lookup, paise-int amounts)
- [ ] `src/saathi/executors/concierge.py` extend — `send_payment_request_to_deep`, `handle_deep_confirmation`
- [ ] `src/saathi/app.py` extend — `POST /telegram/webhook` (chat_id allowlist + secret-token verify)
- [ ] `src/saathi/llm/tools.py` extend — `BILL_TOOLS`
- [ ] `src/saathi/llm/prompts.py` extend — `BILL_SUBAGENT`
- [ ] In-process scheduler for 10-min/1-hr Deep nudges (APScheduler-free: simple `asyncio.create_task` + DDB TTL)
- [ ] Tests + STATUS + DECISIONS (concierge mode is v1 constraint, BBPS path named for v2)

### Acceptance
- [ ] "बिजली का बिल भर दो" → JVVNL bill voice summary ≤30s
- [ ] "हाँ" → Deep Telegram message with payment link ≤5s
- [ ] Deep marks paid + receipt → Mom voice confirmation + image ≤10s
- [ ] Mobile recharge "Jio recharge ₹299" → same flow with Jio link
- [ ] All three flows reachable end-to-end

---

## Day 6 — Polish (मम्मी UX pass)

### Code track (in priority order)
- [ ] **Polish 1** — interim ack ≤2.5s on every voice (3 cached MP3 variants in S3, media_id cached in DDB)
- [ ] **Polish 2** — digit-by-digit amounts ≥ ₹1000 (`rupees_for_confirmation` in `utils/hindi.py`)
- [ ] **Polish 3** — `रोको` / `cancel` / `रद्द करो` abort flag (Haiku stop-keyword classifier on first 3s of new voice, `session.aborted=True`, every tool call checks)
- [ ] **Polish 4** — 8 pre-rendered Hindi failure voices in `messaging/templates.py::FAILURE_VOICES`
- [ ] **Polish 5** — Stagehand fallback for Playwright timeouts in `medicine_1mg.py` and `grocery_blinkit.py`
- [ ] **Polish 6** — confidence-gated escalation (`confirm_understanding` tool, force second confirm if conf < 0.85)
- [ ] **Polish 7** — latency profile, pre-warm Browserbase on grocery/medicine intent, Sarvam keepalive cron
- [ ] `scripts/prerender_system_voices.py` one-shot
- [ ] All existing tests still green; new tests for abort flag and digit-by-digit

### Acceptance
- [ ] Interim ack ≤2.5s
- [ ] Amounts ≥ ₹1000 read twice (natural + digit by digit)
- [ ] `रोको` aborts ≤5s
- [ ] No English fallback strings reach Mom
- [ ] Stagehand recovers from at least one induced selector breakage

---

## Day 7 — Mom uses it for real

### Human track (this is the day)
- [ ] Morning briefing with Mom (5 min)
- [ ] Three guided test orders (grocery, medicine, bill)
- [ ] Afternoon silent observation; CloudWatch + Telegram + S3 tabs open
- [ ] Evening: top 3 fixes, deploy

### Code track (only the docs)
- [ ] `docs/RUNBOOK.md` — healthz, log filters, OTP refresh procedure, rollback, secrets list, template submission
- [ ] `docs/V2_BACKLOG.md` — everything Mom asked for that's not v1
- [ ] `docs/COSTS.md` — actual vs PLAN estimate
- [ ] `docs/STATUS.md` final v1 state
- [ ] `git tag -a v1.0.0 -m "Saathi v1.0.0 — Mom-tested"`

### Acceptance (from PLAN §6 / DAY_7)
- [ ] Grocery order on COD → voice ETA ≤20s
- [ ] Medicine reorder with order ID confirm
- [ ] Bill pay via concierge with receipt image
- [ ] `रोको` mid-flow cancels
- [ ] Same flows work next morning (cookies hold)
- [ ] **4 of 5 = v1 shipped**

---

## Cross-cutting always-on rules (lifted from CLAUDE.md)

- No new dependencies without asking. Stack is locked per CLAUDE.md table.
- No new vendors. Sarvam / Bedrock-Anthropic / Browserbase / DDB / S3 / SQS only.
- Stubs labelled `# STUB: replaced in Day N` and listed in STATUS.md.
- Mom's number is the only allowed sender; reject all others silently.
- `X-Hub-Signature-256` HMAC verified on every webhook (`hmac.compare_digest`).
- No card data, no UPI mandates, no banking creds in v1. COD-only.
- TTS amounts: write ₹ as "रुपये", numbers as Hindi words; digit-by-digit ≥ ₹1000.
- Logging: structured JSON, no voice content, hash transcripts if needed.
