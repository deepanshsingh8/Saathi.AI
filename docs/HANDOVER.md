# Saathi — Handover (read this first)

**Last updated:** 2026-05-14 · **By:** prior Claude Code session · **For:** next session (Claude or human)

This is the start-here doc. Read it once, then jump to the specific files it points at. Everything else (PLAN.md, day briefs, STATUS.md, DECISIONS.md, HUMAN_SETUP.md, the code) is the source of truth — this is just the map.

---

## 1 · The 30-second pitch

Saathi (साथी) is a single-user WhatsApp voice-note assistant for **Deep's mom** in Jaipur (Hindi/Hinglish, ~60). She voice-notes; Saathi orders her medicines (1mg/PharmEasy), groceries (Blinkit/Swiggy Instamart), and pays utility bills (JVVNL electricity, Jio/Airtel recharge — concierge mode). **COD-only.** v1, no payments, no multi-user.

**Stack is locked.** Don't substitute. See §7.

---

## 2 · Where we are right now

| | |
|---|---|
| **Code track** | ✅ **Complete.** Days 1–6 written, all 7 polish gaps closed |
| **Tests** | ✅ **132 passing**, ruff clean (`uv run --extra dev pytest && uv run --extra dev ruff check src tests scripts`) |
| **Real services** | ❌ **Never run.** Every test mocks the boundary. No real Bedrock, Sarvam, AWS, Playwright, Telegram, or WhatsApp call has happened |
| **Human track** | ❌ **Not started.** SIM, Meta app, Lightsail, AWS resources, Sarvam key, Mom's profile data — all pending |
| **Day 7 (Mom uses it live)** | ❌ Blocked by human track |

**Bottom line:** the bot can boot locally and survive `pytest`. It has not yet sent a single real message.

---

## 3 · The four canonical docs (in priority order)

Read these for the *current* state of anything:

1. **[`CLAUDE.md`](../CLAUDE.md)** — project rules, locked stack, scope discipline, Mom's profile, security posture. **Re-read at session start.**
2. **[`docs/STATUS.md`](STATUS.md)** — what's running, what's built per day, what's stubbed, what's locked, what's pending external. **Update at session end.**
3. **[`docs/HUMAN_SETUP.md`](HUMAN_SETUP.md)** — the end-to-end runbook for everything Deep does himself. 15 sections, ~6–8 hours of focused work spread across 3–14 days due to queue waits.
4. **[`docs/DECISIONS.md`](DECISIONS.md)** — every deviation from the briefs, with rationale and reversibility. **Append here whenever you deviate.**

Reference (don't execute from):

- **[`PLAN.md`](../PLAN.md)** at repo root — full strategy, vendor analysis, cost models, Indian-commerce reality check. Reference, not a build spec.
- **[`docs/DAY_1.md`](DAY_1.md) … [`DAY_7.md`](DAY_7.md)** — per-day build briefs. Already executed; revisit only if a Day's acceptance criteria need re-validation post-real-run.

Live state:

- **[`tasks/todo.md`](../tasks/todo.md)** — full Day 1–7 split between human track and code track. Many items are checked but not validated end-to-end.
- **[`tasks/lessons.md`](../tasks/lessons.md)** — empty. Append when Deep corrects you.

---

## 4 · What's done in code (the inventory)

```
src/saathi/
├── app.py                          # /healthz, /webhook (Meta), /telegram/webhook
│                                   #   text/audio/interactive handlers
│                                   #   abort flag, interim ack, lifespan
├── config.py                       # pydantic-settings: WA, AWS, Sarvam, Bedrock,
│                                   #   Browserbase, Telegram, Swiggy MCP
├── lifecycle.py                    # Sarvam keepalive cron + Browserbase pre-warm
├── scheduler.py                    # 10min/1hr Deep nudges (cancellable)
├── messaging/
│   ├── whatsapp.py                 # send_text, download_media, upload_media,
│   │                               #   send_audio, send_buttons, send_image
│   ├── webhooks.py                 # HMAC verify (constant-time), message extract
│   └── templates.py                # 8 FAILURE_VOICES, 5 interim acks
├── speech/
│   ├── sarvam.py                   # AsyncSarvamAI: Saaras v3 + Bulbul v3
│   └── fallback.py                 # Whisper stub
├── llm/
│   ├── prompts.py                  # SAATHI_SYSTEM, intent classifier,
│   │                               #   3 subagent prompts
│   ├── tools.py                    # 11 Anthropic-native tool schemas + filter
│   ├── intent.py                   # Haiku 4.5 classifier
│   ├── orchestrator.py             # Sonnet 4.6 manual tool-use loop +
│   │                               #   button-confirm + SKU guard + abort check
│   │                               #   + confidence gate + Path A/B switch
│   └── abort.py                    # regex stop-keyword classifier
├── executors/
│   ├── medicine_1mg.py             # Browserbase + Playwright
│   ├── grocery_blinkit.py          # Path B default
│   ├── grocery_swiggy.py           # Path A scaffold (gated on whitelist)
│   ├── bill_jvvnl.py               # Public scrape + 1h DDB cache
│   ├── concierge.py                # Telegram: notify + payment-handoff +
│   │                               #   paid/skip + receipt-image forwarding
│   └── fallback.py                 # AI selector recovery (Sonnet-driven)
├── storage/
│   ├── s3.py                       # voice archival (aioboto3)
│   └── dynamo.py                   # single-table client
└── utils/
    ├── hindi.py                    # rupees_to_hindi_words, digit-by-digit,
    │                               #   pronunciation overrides
    └── logging.py                  # structured JSON

scripts/
├── deploy.sh, saathi.service, Caddyfile
├── seed_profile.py, seed_usual_basket.py
├── manual_login_{1mg,pharmeasy,blinkit}.py    # human-driven OTP
├── prerender_system_voices.py                 # one-shot static voice cache
├── smoke_test.py                              # send recorded fixture, watch logs
└── data/usual_basket.template.json
```

**132 tests** in `tests/`, organized by module name.

---

## 5 · What's left to do

### 5.1 Human track (blocking real-world testing)

**See [`docs/HUMAN_SETUP.md`](HUMAN_SETUP.md) §1–§11.** Don't restate it here.

The long-leads worth filing **first** (multi-day SLAs):
- Swiggy MCP whitelist
- 1mg merchant API access
- WhatsApp utility template review (24–48h)

### 5.2 Post-real-run code work (will need new code)

These are **not** done. They need a real first run to inform the change.

| Item | Where | What needs to happen |
|---|---|---|
| Playwright selectors | `medicine_1mg.py`, `grocery_blinkit.py`, `bill_jvvnl.py` (search for `# RE-VALIDATE`) | After Deep's manual logins, load each site, walk the flow with `await page.pause()`, update selectors. Realistic: 50–80% of selector code gets rewritten |
| LLM prompt tuning | `llm/prompts.py` (the `# RE-VALIDATE prompt prose` comment at top) | Run first 5–10 real Sonnet turns; tighten where it doesn't follow the rules (Hindi-words for amounts, no SKU substitution, etc.) |
| `PRONUNCIATION_OVERRIDES` | `utils/hindi.py` | Have Mom say her medicine names; if Bulbul mispronounces, add to dict |
| `TTS_VOICE` decision | `.env` `TTS_VOICE` | Mom listens to vidya/anushka/manisha samples; pick one |
| Voice fixtures | `tests/fixtures/mom_*.oga` | Record Mom saying the canonical test phrases (see `DAY_2.md`) |
| Receipt-image: full WhatsApp upload path | `concierge.handle_deep_confirmation` | Currently uses Telegram CDN URL — works but couples to Telegram's 1h URL TTL. Could re-host on S3 |

### 5.3 Things explicitly deferred to v2 (do NOT build)

If Deep asks for any of these, push back: **"that's v2 per `PLAN.md` §10."**

1. Razorpay agentic UPI / any non-COD payment
2. Multi-user / multi-tenant
3. Family-shared accounts
4. Learning baskets from observed orders
5. BBPS direct integration
6. Swiggy Food / Dineout (Instamart only)
7. WhatsApp Flows
8. Voice cloning
9. Real-time TTS streaming
10. Multi-language beyond Hindi/Hinglish
11. Self-hosted ASR/TTS
12. Web dashboard
13. Computer Use / full agentic vision

---

## 6 · How to work with Deep (read this carefully)

These are durable preferences. Memory file: `feedback_build_cadence.md` in the project memory dir (`/Users/deepanshsingh/.claude/projects/-Users-deepanshsingh-Desktop-Personal-Saathi-AI/memory/`).

| Preference | Implication |
|---|---|
| **Senior dev, knows AWS/Python/IoT/MCP** | Don't over-explain Python/AWS basics. Skip the apologies and the "great question." |
| **Direct, no fluff** | Match the tone. Honest about uncertainty. No padding. |
| **Code-first build cadence** | When given a multi-day plan, write all code ahead and batch human steps. Accept rework on Playwright selectors and LLM prompts as the cost. **Do not re-ask** whether to wait for human steps. |
| **Scope discipline** | If a request straddles days, push back: *"that's Day N, want me to do it now or stay on Day M?"* Per project `CLAUDE.md`. |
| **No silent dep additions** | Surface new deps before adding. If a brief's pin doesn't exist on PyPI (the `sarvamai==4.23.2` problem), document the deviation in `DECISIONS.md`. |
| **No stubs without labels** | `# STUB: replaced in Day N` and listed in `STATUS.md`. |
| **No new vendors** | Sarvam / Bedrock-Anthropic / Browserbase / DDB / S3 / SQS only. If something seems to need Twilio/Postgres/Pinecone, stop and ask. |

The one place this conflicts with project `CLAUDE.md`: the `CLAUDE.md` says *"one slice per session — land a working, committed, tested change before the next thing."* Deep has explicitly overridden this for the v1 build (he wants code-first batching). After v1 ships, default back to one-slice-per-session.

---

## 7 · The locked stack (don't substitute)

| Layer | Choice | Don't substitute |
|---|---|---|
| Language | Python 3.12 | not 3.11, not 3.13 (3.14 has wheel issues for pydantic-core 2.23) |
| Web | FastAPI 0.115 | not Flask, not Django |
| LLM | Claude Sonnet 4.6 (orchestrator), Haiku 4.5 (intent), via Bedrock `ap-south-1` | not OpenAI, not Gemini |
| LLM SDK | `anthropic` direct (NOT `claude-agent-sdk` — see [DECISIONS](DECISIONS.md) `2026-05-14 · Orchestrator: anthropic SDK direct`) | |
| Speech | `sarvamai==0.1.28` (Saaras v3 STT, Bulbul v3 TTS) | Whisper only as fallback |
| Browser | Playwright 1.49 + Browserbase 1.10 | not Selenium |
| Browser AI fallback | Sonnet-driven via `executors/fallback.py` (NOT `stagehand` — that PyPI package is a cloud REST client, not what we need) | |
| WhatsApp | Meta Cloud API direct (graph.facebook.com v22.0) | not Twilio, not AiSensy/Wati/Interakt |
| State | DynamoDB single table `saathi` in `ap-south-1` | not Postgres, not Redis |
| Media | S3 bucket `saathi-media` in `ap-south-1` | |
| Secrets | AWS Secrets Manager | not .env in production |
| Queue | SQS for webhook ack→worker (not yet wired — Day 6 polish if latency hurts) | not Celery, not RQ |
| Host | AWS Lightsail Mumbai (2 GB) | |
| HTTP | Caddy (auto-HTTPS) | not Nginx for v1 |
| Local env | `uv` for venv + deps, `ruff` for lint/format, `pytest` for tests | |
| Concierge alerts | Telegram bot (httpx-only — no python-telegram-bot SDK) | |

Pinned dep deltas from briefs (already documented in `DECISIONS.md`):
- `boto3==1.35.36` (was `1.35.0` in brief — incompat with aioboto3)
- `sarvamai==0.1.28` (was `4.23.2` — version doesn't exist)
- `pydantic-settings>=2.5.2` (was `==2.5.0` — needed by mcp)
- `mcp>=1.9.0` (was 1.1.3 — needed by claude-agent-sdk)
- ruff `line-length=110` (was 100 — Hindi prompts + Playwright selectors)

---

## 8 · First moves for the next session

When you pick this up:

```bash
# 1. Sanity check
cd /Users/deepanshsingh/Desktop/Personal/Saathi.AI
uv run --extra dev pytest -q          # expect: 132 passed
uv run --extra dev ruff check src tests scripts   # expect: All checks passed!

# 2. Read state
cat docs/STATUS.md                    # what's actually running
cat docs/DECISIONS.md                 # what we decided + why
cat tasks/todo.md                     # what's checked vs not

# 3. Listen for the user's intent
```

If the user says **"is the human setup done?"** → ask which steps in `HUMAN_SETUP.md §1–§11` they've completed. If `§11` smoke test passed, jump to §9 (post-real-run tuning).

If the user says **"selectors are wrong on 1mg"** (or similar) → grep for `# RE-VALIDATE` in `src/saathi/executors/`, ask them to share the actual page HTML or run with `page.pause()`, update selectors. Test with `scripts/smoke_test.py --flow medicine --dry-run`.

If the user says **"Sonnet is doing X wrong"** → look at `src/saathi/llm/prompts.py`. The subagent prompts are tunable. Tighten with explicit examples of the desired behavior.

If the user says **"add a feature"** → check it against `PLAN.md §10` deferred list. If it's there, push back. If not, ask which day's brief it fits.

---

## 9 · Post-real-run tuning order (when human track is done)

This is the playbook for the **first real session** with Mom on the line:

1. **Pre-render system voices**: `uv run python scripts/prerender_system_voices.py` (one-shot)
2. **Seed Mom's profile**: `uv run python scripts/seed_profile.py --file ~/saathi-private/profile.json`
3. **Seed usual basket**: `uv run python scripts/seed_usual_basket.py --file ~/saathi-private/usual_basket.json`
4. **Smoke text echo** (Day 1 acceptance): Mom sends `hello` → expect Hindi greeting ≤5s
5. **Smoke voice echo** (Day 2 acceptance): Mom voice-notes → expect voice reply ≤6s
6. **First medicine order, dry-run**: `scripts/smoke_test.py --flow medicine --dry-run` — watch CloudWatch / `journalctl -u saathi -f`
7. **Selector fix sprint**: every `RE-VALIDATE` site, walk it interactively, update `src/saathi/executors/*`
8. **First real medicine order** (no dry-run): observe latency, prompt compliance
9. **First grocery order**
10. **First bill** (concierge mode → Telegram → Deep marks paid → Mom gets receipt)
11. **Day 7 ritual**: write `RUNBOOK.md`, `V2_BACKLOG.md`, `COSTS.md`. Tag `v1.0.0`.

---

## 10 · Open known gotchas

| Gotcha | Where you'll see it | Fix |
|---|---|---|
| Bulbul mispronounces brand names | Mom complains the medicine name sounds wrong | Add to `PRONUNCIATION_OVERRIDES` in `utils/hindi.py` |
| 1mg / Blinkit cookies expire ~30 days | Executor raises `ExecutorError("session_expired")`; orchestrator notifies Deep | Re-run `scripts/manual_login_*.py`, re-upload to Secrets Manager |
| Browserbase free tier (1 browser-hour/month) | First medicine flow on Day 3 likely exhausts it | Upgrade to Developer plan ($20/mo) |
| Bedrock cold start in ap-south-1 | First call of the day ~200ms slower | Sarvam keepalive (already wired) doesn't cover this; provisioned throughput is overkill for v1 |
| WhatsApp 24h customer-service window closes | Outbound message after window → 131047 error | Saathi's 3 utility templates handle status pings outside window. If the window closes mid-flow, switch to template |
| Selector fallback over-recovers | Bot clicks the wrong button via AI fallback | `executors/fallback.py` — tighten `SELECTOR_PROMPT`, or add an allow-list of intents that can use fallback |
| AI selector fallback adds ~2s latency | Visible during recovery | Document on Day 7; consider caching the recovered selector to a local map |
| Telegram getFile URL TTL ~1h | If Deep's receipt forward arrives but Mom doesn't open WhatsApp for >1h, the image link breaks | Re-host on S3 if this becomes a real issue (post-launch) |

---

## 11 · Memory and persistence

- **Project memory**: `/Users/deepanshsingh/.claude/projects/-Users-deepanshsingh-Desktop-Personal-Saathi-AI/memory/`
  - `feedback_build_cadence.md` — Deep prefers code-first builds, batched humans, accept rework
  - `MEMORY.md` — index
- **Tasks (current session)**: `tasks/todo.md`, `tasks/lessons.md` (append from corrections)
- **Persistent build state**: `docs/STATUS.md` (single source of truth — update at session end)
- **Architecture decisions**: `docs/DECISIONS.md` (append on every deviation)

---

## 12 · The "if everything is broken" reset

```bash
ssh ubuntu@<lightsail-ip>
sudo systemctl stop saathi          # safe — Mom gets no reply, no error
sudo systemctl start saathi         # bring back
git log --oneline -10               # find the good commit
git checkout <sha>                  # roll back if recent commit broke it
sudo systemctl restart saathi
```

If `.env` got corrupted: there's no in-repo backup (it's `.gitignore`d). Deep keeps a copy at `~/saathi-private/.env.backup` per `HUMAN_SETUP.md §11`.

---

**That's the handover.** When in doubt, read `STATUS.md` → `DECISIONS.md` → ask Deep. He'd rather answer one question than rewrite a misaligned module.

— prior Claude Code session, signing off
