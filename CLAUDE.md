# Saathi — Claude Code Instructions

You are working on **Saathi**, a WhatsApp voice-note assistant for Deep's mom (Hindi/Hinglish-speaking, Jaipur). She sends voice notes; Saathi orders groceries, medicines, and pays utility bills on her behalf.

## Read these first, every session

1. **`docs/PLAN.md`** — the full strategy doc. Architecture, vendor choices, policy reasoning. Reference, not a build spec.
2. **`docs/DAY_<N>.md`** — the day-N build brief. **This is what you actually execute.** It has scope, file paths, acceptance criteria, and explicit boundaries.
3. **`docs/STATUS.md`** — what's been built, what's broken, what's deferred. Update at the end of every session.

If the user pastes a task without telling you which day they're on, ask. Don't guess across days.

## The non-negotiables

- **Scope discipline.** If a request lies outside the current day's brief, push back. Say "that's Day N, want me to do it now or stay on Day M?" Do not silently expand scope.
- **One slice per session.** Land a working, committed, tested change before starting the next thing. No half-built parallel branches.
- **No mocking past the file boundary.** Stubs are fine inside a module if a dependency hasn't been built yet (Day 3 can stub the executor that Day 4 builds), but the stub must be *labelled* with `# STUB: replaced in Day N` and listed in `docs/STATUS.md` under "Stubs". Mocks in tests are fine.
- **No new dependencies without asking.** The stack is locked (see below). If something seems to need a new library, surface it first.
- **No new vendors without asking.** Sarvam for speech, Anthropic via Bedrock for LLM, Browserbase for browser, DynamoDB for state, S3 for media. If the work seems to need something else (e.g. Twilio, Postgres, Pinecone), stop and ask.
- **No code execution against production accounts in this repo's tests.** Real WhatsApp sends, real Blinkit orders, real Sarvam calls happen only from `scripts/` invoked by Deep manually. Tests use recorded fixtures.

## The user (Deep)

- Senior developer. Knows AWS, Python, Claude Code, MCP, IoT. Don't over-explain Python or AWS basics.
- Based in Jaipur. AWS region is `ap-south-1` (Mumbai). All infra defaults to Mumbai.
- Prior projects: Aqueduct (water IoT), Ragify (edu RAG). Familiar with DynamoDB single-table patterns.
- Communication: direct, no fluff, honest about uncertainty. Don't pad responses with apologies or "great question."

## The end user (Mom)

- Hindi/Hinglish speaker, ~60, WhatsApp-fluent but not app-fluent.
- Jaipur, PIN 302017 area (verify in profile).
- Voice-first. Never assume she'll read or type. Buttons OK, text replies as a fallback only.
- Conservative with money. Read amounts ≥ ₹100 digit-by-digit in confirmations.

## Stack (locked for v1)

| Layer | Choice | Don't substitute |
|---|---|---|
| Language | Python 3.12 | |
| Web framework | FastAPI | Not Flask, not Django |
| LLM | Claude Sonnet 4.6 (orchestrator), Haiku 4.5 (intent), via AWS Bedrock `ap-south-1` | Not OpenAI, not Gemini |
| LLM SDK | `claude-agent-sdk` (Python) | |
| Speech | Sarvam Saaras v3 (STT), Bulbul v3 (TTS) | Whisper only as fallback |
| Browser | Playwright + Browserbase | Not Selenium |
| WhatsApp | Meta Cloud API direct (graph.facebook.com) | Not Twilio, not AiSensy/Wati/Interakt |
| State | DynamoDB single table `saathi` in `ap-south-1` | Not Postgres, not Redis |
| Media | S3 bucket `saathi-media` in `ap-south-1` | |
| Secrets | AWS Secrets Manager | Not .env in production |
| Queue | SQS for webhook ack→worker | Not Celery, not RQ |
| Host | AWS Lightsail Mumbai (2 GB) | |
| HTTP | Caddy (auto-HTTPS) | Not Nginx for v1 |
| Local env | `uv` for venv + deps, `ruff` for lint/format, `pytest` for tests | |
| Concierge alerts | Telegram bot (Deep's personal account) | |

## Repo layout

```
saathi/
├── CLAUDE.md                  # this file
├── README.md                  # human-facing project overview
├── pyproject.toml             # uv-managed, ruff config inline
├── docs/
│   ├── PLAN.md                # full strategy (reference)
│   ├── DAY_1.md … DAY_7.md    # per-day build briefs (execute these)
│   ├── STATUS.md              # running state of the build
│   └── DECISIONS.md           # ADR-style log of choices that deviated from PLAN
├── src/saathi/
│   ├── __init__.py
│   ├── app.py                 # FastAPI app, webhook routes
│   ├── config.py              # env vars, constants
│   ├── messaging/
│   │   ├── whatsapp.py        # Cloud API client
│   │   ├── templates.py       # template names + bodies
│   │   └── webhooks.py        # inbound webhook parsing + sig verify
│   ├── speech/
│   │   ├── sarvam.py          # Saaras STT + Bulbul TTS
│   │   └── fallback.py        # Whisper fallback
│   ├── llm/
│   │   ├── orchestrator.py    # main Sonnet agent loop
│   │   ├── intent.py          # Haiku intent classifier
│   │   ├── prompts.py         # system prompts (Hindi-aware)
│   │   └── tools.py           # tool definitions for Sonnet
│   ├── executors/
│   │   ├── medicine_1mg.py    # Playwright on 1mg or PharmEasy
│   │   ├── grocery_blinkit.py # Playwright on Blinkit
│   │   ├── grocery_swiggy.py  # Swiggy Instamart MCP client (if whitelisted)
│   │   ├── bill_jvvnl.py      # JVVNL bill fetch (Playwright)
│   │   └── concierge.py       # Telegram bot for bill-pay human-in-loop
│   ├── storage/
│   │   ├── dynamo.py          # single-table client
│   │   └── s3.py              # media bucket client
│   └── utils/
│       ├── hindi.py           # number/amount formatting for TTS
│       └── logging.py         # CloudWatch + structured logs
├── tests/
│   ├── fixtures/              # recorded voice notes, sample webhook payloads
│   ├── test_messaging.py
│   ├── test_speech.py
│   ├── test_llm.py
│   └── test_executors.py
└── scripts/
    ├── seed_profile.py        # one-time DDB seed of mom's profile
    ├── manual_login_1mg.py    # human-driven OTP login, saves storage_state
    ├── manual_login_blinkit.py
    ├── refresh_session.py     # re-OTP when cookies expire
    └── smoke_test.py          # end-to-end test against real services
```

## Coding conventions

- **Type hints everywhere.** `from __future__ import annotations` at the top of every module.
- **Async by default** for anything that touches I/O (WhatsApp, Sarvam, Bedrock, DynamoDB via aioboto3, Playwright async API).
- **Functions over classes** unless you need state or polymorphism. Saathi is mostly pipelines.
- **One module = one responsibility.** If `medicine_1mg.py` starts talking to S3, move the S3 call to `storage/s3.py` and import it.
- **No global singletons except the FastAPI app.** Pass clients (DDB, S3, WhatsApp, Sarvam) as function args or via FastAPI dependency injection.
- **Errors:** raise specific exceptions (`SarvamError`, `WhatsAppError`, `ExecutorError`). Catch only at the worker boundary, log structured, and reply to mom in Hindi via `messaging.whatsapp.send_failure_voice()`.
- **Logging:** structured JSON to stdout (CloudWatch picks it up). Include `conv_id`, `intent`, `tool`, `latency_ms`. Never log voice content (privacy); log the transcript hash if needed.
- **No print().** Use the logger.
- **Tests:** `pytest`, async tests with `pytest-asyncio`. Fixtures in `tests/fixtures/`. Mock external HTTP with `respx` for httpx clients. Don't mock our own code.

## Hindi/Hinglish specifics

- TTS input: write out numbers in Hindi words for amounts (`₹3,240` → `तीन हज़ार दो सौ चालीस रुपये`). Use the helper in `utils/hindi.py`.
- Brand names: maintain `utils/hindi.py::PRONUNCIATION_OVERRIDES` dict for medicines Bulbul mispronounces (e.g. `Telma` → `टेल्मा`).
- STT output: prefer `mode="codemix"` for natural Hindi-English mix; switch to `mode="transcribe"` when you want pure Devanagari (e.g. for stored transcript audit logs).
- The bot is named **Saathi** (साथी, "companion"). She refers to herself as `मैं Saathi` in voice, never "I am an AI."
- Failure messages are in Hindi. Pre-write 8 of them in `messaging/templates.py::FAILURE_VOICES`.

## Security & privacy

- Mom's number is the **only** allowed sender in v1. Reject all others silently (return 200 to Meta, log, drop).
- Voice notes encrypted at rest (S3 SSE-KMS).
- Playwright `storage_state.json` (mom's logged-in cookies for 1mg/Blinkit) lives in Secrets Manager, never in git, never in DDB.
- WhatsApp `X-Hub-Signature-256` HMAC verified on every webhook. Reject mismatches with 401.
- No card data, no UPI mandates, no banking credentials touched in v1. COD-only.
- The Telegram concierge bot is Deep-only; verify `chat_id` on every incoming Telegram update.

## What's deferred to v2 (do NOT build these)

If the user asks for any of these, say "that's v2 per PLAN §10, want to add to backlog or are we changing scope?":

1. Razorpay agentic UPI / any non-COD payment
2. Multi-user / multi-tenant
3. Family-shared accounts (adult-child sets up for parent)
4. Learning from observed orders (pre-set baskets only in v1)
5. BBPS direct integration
6. Swiggy Food / Dineout (Instamart only)
7. WhatsApp Flows
8. Voice cloning
9. Real-time TTS streaming via WebSocket
10. Multi-language beyond Hindi/Hinglish
11. Self-hosted ASR/TTS
12. Web dashboard
13. Computer Use / full agentic vision (Stagehand for selector resilience is OK)

## When you finish a session

Update `docs/STATUS.md` with:
- What's done (file paths, what each module now does)
- What's stubbed (and which Day will replace each stub)
- What broke (open issues)
- Any decisions that deviated from PLAN.md (add to `docs/DECISIONS.md`)

That's the handoff to the next session. Keep it terse and accurate.

## When you're unsure

Ask Deep. He'd rather answer one question than rewrite a misaligned module. The bot is for his mom; getting it right matters more than getting it fast.
