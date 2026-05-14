# Saathi — Build Status

**Update this at the end of every session.** Terse, accurate, recent-first.

---

## Days 1–6 — code track done 2026-05-14 (human track unstarted)

### Running (locally only)
- `uv run uvicorn saathi.app:app` boots cleanly on Python 3.12.13
- **101/101 tests green** (`uv run --extra dev pytest`); ruff clean
- End-to-end voice/order flows NOT yet validated against real services — that
  needs the human track (Sarvam key, Bedrock access, Lightsail box, manual OTP
  logins, Mom's seeded profile). See `docs/HUMAN_SETUP.md`.

### Built — Day 1 (echo)
- `src/saathi/config.py`, `src/saathi/utils/logging.py`
- `src/saathi/messaging/{whatsapp,webhooks}.py` — `send_text` + `WhatsAppError`,
  `verify_signature` + `extract_message`
- `src/saathi/app.py` — `/healthz`, GET/POST `/webhook`, mom-only filter,
  BackgroundTasks dispatch, `handle_text_message` echo
- `tests/conftest.py`, `tests/test_messaging.py`
- `scripts/{deploy.sh,saathi.service,Caddyfile}`

### Built — Day 2 (voice)
- `src/saathi/storage/s3.py` — aioboto3 voice archival
- `src/saathi/speech/sarvam.py` — Saaras v3 STT, Bulbul v3 TTS via
  `AsyncSarvamAI` (sarvamai==0.1.28)
- `src/saathi/speech/fallback.py` — Whisper stub
- `src/saathi/utils/hindi.py` — `rupees_to_hindi_words` (0..9_99_99_999),
  `rupees_for_confirmation` (digit-by-digit ≥ ₹1000),
  `apply_pronunciation_overrides`, `PRONUNCIATION_OVERRIDES` dict (6 seeded)
- `src/saathi/messaging/whatsapp.py` extended — `download_media`,
  `upload_media`, `send_audio`, `send_buttons`
- `src/saathi/app.py::handle_audio_message` — download → S3 → STT → route
- `tests/test_{hindi,speech,storage}.py`

### Built — Day 3 (LLM + medicine)
- `src/saathi/storage/dynamo.py` — single-table client (profile, sessions,
  orders, meds, basket, bill cache, pending bills)
- `src/saathi/llm/intent.py` — Haiku 4.5 classifier, JSON-only, codefence-tolerant
- `src/saathi/llm/prompts.py` — `INTENT_CLASSIFIER`, `SAATHI_SYSTEM`,
  `MEDICINE_SUBAGENT`, `GROCERY_SUBAGENT`, `BILL_SUBAGENT`
- `src/saathi/llm/tools.py` — Anthropic-native tool schemas + `tools_for(intent)`
- `src/saathi/llm/orchestrator.py` — Sonnet 4.6 manual tool-use loop,
  button-confirm pattern via DDB session, SKU guard, abort flag check,
  `resume_after_button`
- `src/saathi/executors/medicine_1mg.py` — Browserbase + Playwright (selectors
  marked `# RE-VALIDATE`)
- `src/saathi/executors/concierge.py` — `notify_deep` (Day 3) +
  `send_payment_request_to_deep` + `handle_deep_confirmation` (Day 5)
- `src/saathi/app.py` extended — voice → intent → orchestrator routing,
  interactive button replies (`handle_interactive_message`),
  `_LATEST_PTR` for single-user conv tracking
- `scripts/{seed_profile,manual_login_1mg,manual_login_pharmeasy,smoke_test}.py`
- `tests/test_{intent,tools,orchestrator,concierge}.py`

### Built — Day 4 (grocery)
- `src/saathi/executors/grocery_blinkit.py` — Path B default. `search_blinkit`,
  `add_to_cart`, `get_cart`, `checkout_cod`, `check_pin_serviceable` (selectors
  marked `# RE-VALIDATE`)
- `src/saathi/executors/grocery_swiggy.py` — Path A scaffolded; `is_enabled()`
  gate on `SWIGGY_MCP_URL` + creds
- `scripts/{manual_login_blinkit,seed_usual_basket}.py` +
  `scripts/data/usual_basket.template.json`
- `tests/test_executors.py` — parser + error helpers

### Built — Day 5 (bill pay concierge)
- `src/saathi/executors/bill_jvvnl.py` — Playwright fetch (no login),
  paise-int amounts, 1h DDB cache (selectors `# RE-VALIDATE`)
- `src/saathi/app.py::POST /telegram/webhook` — secret-token verify +
  chat_id allowlist + paid/skip dispatch
- `tests/test_telegram_webhook.py` — 6 routing tests

### Built — Day 6 (polish — all 7 closed)
- `src/saathi/messaging/templates.py` — 8 `FAILURE_VOICES`, 3 interim acks,
  3 slow-track interim acks, `failure_voice(key, **fmt)`, `random_interim_ack`
- `src/saathi/llm/abort.py` — regex stop-keyword classifier (cheap; no LLM call)
- `src/saathi/app.py::_send_failure_voice` — DDB media_id cache lookup,
  Sarvam fallback
- `src/saathi/app.py::handle_audio_message` — pre-STT abort check + interim-ack
  emission within ~2s of voice arrival (Gap 1)
- `scripts/prerender_system_voices.py` — one-shot to render + cache static voices
- `src/saathi/scheduler.py` — 10min Mom nudge + 1hr Deep escalation, cancellable
  on resolution (Gap 2)
- `src/saathi/llm/orchestrator.py::_check_confidence_gate` — server-side refusal
  of high-stakes tools when last `confirm_understanding` confidence < 0.85 (Gap 3)
- `src/saathi/executors/fallback.py` — AI selector recovery via Sonnet ("which
  CSS selector matches this intent?") wrapping critical Playwright actions in
  `medicine_1mg.place_medicine_order` and `grocery_blinkit.checkout_cod` (Gap 4)
- `src/saathi/llm/orchestrator.py::_grocery_executor` — Path A/B switch consults
  `grocery_swiggy.is_enabled(settings)` per call (Gap 5)
- `src/saathi/messaging/whatsapp.py::send_image` + `concierge.fetch_telegram_photo_url`
  + `app.py` Telegram inbound photo handler with token extraction (Gap 6)
- `src/saathi/lifecycle.py` — Sarvam keepalive cron (4-min ping) + Browserbase
  pre-warm on intent=medicine|grocery, 120s TTL pool (Gap 7)
- `tests/test_polish.py`, `tests/test_scheduler.py`, `tests/test_lifecycle.py`,
  `tests/test_fallback.py`, `tests/test_orchestrator_gates.py`,
  `tests/test_telegram_photo.py` — coverage for all 7 gaps

### Test count
- **132 tests passing**, ruff clean

### Stubbed
- `src/saathi/speech/fallback.py` — Whisper backup (replaced when first Sarvam
  429 hits production)
- `src/saathi/executors/grocery_swiggy.py` — full implementation when Swiggy
  MCP whitelist arrives
- `src/saathi/executors/concierge.py::handle_deep_confirmation` — receipt-image
  forwarding to Mom is left as voice-only for v1

### Locked decisions (delta from briefs — see DECISIONS.md)
- Stack per `CLAUDE.md` — Python 3.12, FastAPI, Sonnet 4.6 via Bedrock ap-south-1
- COD-only for v1; single-user (Mom-only)
- `boto3==1.35.36` (was `1.35.0`); `sarvamai==0.1.28` (was `4.23.2` — that
  version doesn't exist); `pydantic-settings>=2.5.2`; `mcp>=1.9.0`
- Orchestrator uses **anthropic SDK direct** (not `claude-agent-sdk`)
- Grocery defaults to **Path B (Blinkit Playwright)**; Path A scaffolded
- **Concierge mode** for bill pay is v1; BBPS path named for v2
- httpx-only Telegram (no `python-telegram-bot` SDK)
- ruff line-length bumped 100 → 110

### Pending external (human track — see docs/HUMAN_SETUP.md)
Everything in HUMAN_SETUP §1 through §11. Long-leads:
- Swiggy MCP whitelist (filed in §1.1 — 3–14d SLA)
- 1mg merchant API (filed in §1.2 — 3–14d SLA)
- WhatsApp templates `saathi_order_status` + `_v2` (submitted in §3.7 — 24–48h)

### Bugs / known issues
- (none locally — all 132 tests green; ~5 files marked `# RE-VALIDATE` for
  Playwright selector + LLM prompt tuning after first real run)

### Next
- **Human track**: complete `docs/HUMAN_SETUP.md` §1–§11 (cost ~₹2k one-time + ~₹4k/mo)
- **Day 7 (post-human)**: sit with Mom for the first real session; observe;
  apply top 3 fixes from CloudWatch + Telegram + S3 logs

---

### Running (locally)
- `uv run uvicorn saathi.app:app` boots cleanly on Python 3.12.13
- 14/14 tests green (`uv run --extra dev pytest -q`); ruff clean
- Echo loop NOT yet validated end-to-end — needs Lightsail + Meta wiring (human track)

### Built
- `tasks/todo.md` — Day 1–7 split between human and code tracks
- `tasks/lessons.md` — empty append-only log
- `README.md` — one-paragraph project blurb
- `src/saathi/config.py` — pydantic-settings (Day 1 fields only: WA_*, AWS, log)
- `src/saathi/utils/logging.py` — structured JSON logger (stdout, never logs voice content)
- `src/saathi/messaging/whatsapp.py` — `send_text(to, body) -> wamid` + `WhatsAppError`
- `src/saathi/messaging/webhooks.py` — `verify_signature` (HMAC, constant-time) + `extract_message`
- `src/saathi/app.py` — `GET /healthz`, `GET /webhook` handshake, `POST /webhook` (HMAC-verified, mom-only, BackgroundTasks dispatch), `handle_text_message` echo
- `tests/conftest.py` + `tests/test_messaging.py` — sig verify (4), webhook routing (6), send_text via respx (3), handle_text_message (1)
- `scripts/deploy.sh`, `scripts/saathi.service`, `scripts/Caddyfile` — Lightsail ops

### Stubbed
- (none — Day 1 has no stubs)

### Pending external (human track — Deep does these)
- SIM purchase + Meta app + System User token + template `saathi_order_status` submitted
- Swiggy MCP whitelist issue filed
- 1mg merchant API request emailed
- AWS Bedrock model access for `claude-sonnet-4-6` and `claude-haiku-4-5` in `ap-south-1`
- Sarvam / Browserbase / Telegram BotFather signups
- Lightsail Mumbai 2 GB provisioned, `saathi.<domain>` DNS pointed, Caddy live
- Mom's data: address, 8–10 grocery items, 5–8 medicines (photographed), JVVNL consumer #, mobile recharge, prescription image, recorded consent

### Locked decisions
- Stack per `CLAUDE.md` — Python 3.12, FastAPI, Sonnet 4.6 via Bedrock ap-south-1, Sarvam STT/TTS, Playwright + Browserbase, DDB single-table, Lightsail Mumbai
- COD-only for v1
- Single-user (Mom's number hardcoded; non-mom senders silently 200'd + logged)
- boto3 pinned at `1.35.36` (was `1.35.0` in Day 1 brief; bumped for aioboto3 13.2.0 compat — see DECISIONS.md)

### Bugs / known issues
- (none locally — end-to-end test gated on human track)

### Next
- **Human track**: complete Block A–E from `docs/DAY_1.md`, deploy to Lightsail, wire Meta webhook, run smoke test
- **Day 2 (code track)**: voice in/out — `speech/sarvam.py`, `storage/s3.py`, extend `whatsapp.py` with media download/upload/send_audio, `utils/hindi.py` with rupees-to-words

---

<!--
TEMPLATE FOR EACH DAY — copy-paste below this comment, fill in:

## Day N — done <YYYY-MM-DD>

### Running
- <component>: <one-line state>

### Built
- `src/saathi/...` — <what each new module does, one line each>

### Locked decisions
- <any choice that's now permanent for v1>

### Stubbed
- `<path>` — <what's stubbed, which Day will replace>

### Bugs / known issues
- <issue> — <severity, plan>

### Pending external
- <waiting on Swiggy / 1mg / Meta template / whatever>

### Latency (P50, last 10 turns)
- STT: Xms · LLM: Xms · TTS: Xms · executor: Xms · total: Xs

### Cost so far (cumulative)
- Lightsail: ₹X · Bedrock: ₹X · Sarvam: ₹X · Browserbase: ₹X · DDB: ₹X · WhatsApp: ₹X

### Next
- **Day N+1**: <one-line goal>

-->
