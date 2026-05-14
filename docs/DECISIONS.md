# Saathi — Architecture Decisions

Lightweight ADR log. One entry per deviation from `docs/PLAN.md` or per choice made that wasn't pre-decided.

Format:
- **Date · Topic**
- **Context**: why this came up
- **Decision**: what was chosen
- **Alternatives considered**: what wasn't chosen and why
- **Reversibility**: easy / medium / hard
- **Revisit when**: trigger condition for reconsidering

---

## 2026-05-14 · ruff line-length 100 → 110

**Context**: `docs/DAY_1.md` Task 1 specifies `line-length = 100`. Several files (Hindi prompt strings in `llm/prompts.py`, Playwright selectors in executors, tool-schema dict literals in `llm/tools.py`) routinely exceed by 1–10 chars. Forcing wraps either splits Hindi sentences across lines or uglies up declarative dict literals.

**Decision**: Bump to 110. Industry default for modern Python is 88–120; 110 is a small relaxation that covers ~95% of the long-line noise while still flagging genuinely runaway lines.

**Reversibility**: trivial.

---

## 2026-05-14 · Path B (Blinkit Playwright) chosen as default for grocery

**Context**: `docs/DAY_4.md` defines Path A (Swiggy Instamart MCP) and Path B (Playwright on Blinkit). Path A is gated on a manual whitelist (`Swiggy/swiggy-mcp-server-manifest`, 3–14 day SLA per PLAN §3.3) which has not arrived as of build time.

**Decision**: Build Path B as the default. Path A is scaffolded in `src/saathi/executors/grocery_swiggy.py` with `is_enabled(settings)` returning False unless `SWIGGY_MCP_URL` + `SWIGGY_CLIENT_ID` + `SWIGGY_CLIENT_SECRET` are all populated. Orchestrator dispatch can be flipped without code changes once those env vars are set.

**Alternatives considered**: wait for the whitelist before shipping grocery. Rejected — Mom's first grocery order can't be gated on Swiggy's queue.

**Reversibility**: easy — add the three env vars, swap orchestrator's grocery executor import. Tools schema is identical.

**Revisit when**: Swiggy MCP whitelist arrives.

---

## 2026-05-14 · Concierge mode is a v1 constraint, not a permanent design

**Context**: `docs/DAY_5.md` ships bill-pay as a Deep-in-the-loop concierge flow (`request_payment_via_deep` tool → Telegram → Deep taps "Mark Paid" → Saathi voice-confirms to Mom). Mom never sees the handoff.

**Decision**: Concierge mode is the v1 path because real autonomous bill-pay requires either BBPS biller-side onboarding (weeks of RBI-driven KYC) or storing Mom's banking credentials (a hard no for v1). v2 swaps the "ping Deep" step for an API call without changing Mom's UX.

**v2 path forward (named, not built)**:
- **Cashfree BBPS Biller API** (`cashfree.com/bbps`) — supports the payer-side; merchant agreement required.
- **Razorpay Bharat BillPay API** — alt; same KYC pattern.
- **Razorpay agentic UPI** (`razorpay.com/agentic-payments`) — ideal long-term: covers Zomato/Swiggy/Zepto already, BBPS rollout in pilot.

**Reversibility**: easy at the tool level (`request_payment_via_deep` becomes `place_bill_payment`); medium at the policy level (KYC + merchant agreement required first).

**Revisit when**: Razorpay agentic UPI invitation arrives, or Cashfree BBPS onboarding completes.

---

## 2026-05-14 · httpx-only Telegram (no `python-telegram-bot` SDK)

**Context**: `docs/DAY_5.md` left it as a choice: `python-telegram-bot==21.5` or httpx direct.

**Decision**: httpx direct. Telegram bot API is REST + JSON; the SDK adds polling/dispatcher infrastructure we don't use (we use a webhook). Saves a dependency and eliminates the polling-vs-webhook footgun.

**Reversibility**: trivial.

---

## 2026-05-14 · Orchestrator: anthropic SDK direct (not claude-agent-sdk)

**Context**: `docs/DAY_3.md` and `PLAN.md` §4.2 reference `claude-agent-sdk.query()` for the agent loop. The installed `claude-agent-sdk==0.1.69` is built to *spawn the Claude Code CLI as a subprocess* (`cli_path`, `add_dirs`, `cwd` fields) — not embed in a server.

**Decision**: Use `anthropic.AsyncAnthropicBedrock` (or `AsyncAnthropic` fallback) with a manual tool-use loop in `src/saathi/llm/orchestrator.py`. Same agent-loop shape, more predictable, easier to mock in tests, no subprocess dependency.

**Alternatives considered**:
- Stick with `claude-agent-sdk` and spawn the CLI from inside the server. Adds a subprocess + filesystem dependency for no clear benefit.
- Use a third-party agent framework (LangChain/LlamaIndex). Adds dep weight and abstraction we'd fight.

**Reversibility**: medium — would require rewriting `orchestrator.py::run_turn` and the tool-dispatch table.

**Revisit when**: Anthropic ships a server-embedded agent SDK, or `claude-agent-sdk` adds an in-process mode.

---

## 2026-05-14 · sarvamai pin (4.23.2 → 0.1.28)

**Context**: `docs/DAY_2.md` pins `sarvamai==4.23.2`. That version does not exist on PyPI — latest is `0.1.28`. The brief was likely speculating about a future version line.

**Decision**: Pin to `0.1.28` (current latest). API surface verified: `SarvamAI/AsyncSarvamAI` clients with `speech_to_text.transcribe(file=..., model='saaras:v3', mode='codemix', language_code='hi-IN', input_audio_codec='ogg')` and `text_to_speech.convert(text=..., target_language_code='hi-IN', speaker='vidya', model='bulbul:v3', output_audio_codec='mp3', ...)`. Returns `.transcript` (str) and `.audios` (list of base64 strings; concat + decode for bytes).

**Alternatives considered**: write against the brief's imagined 4.x API and hope it ships — would not run.

**Reversibility**: easy — bump pin and rewrite `src/saathi/speech/sarvam.py` if the SDK ships a major version with a different surface.

**Revisit when**: sarvamai 0.2+ or 1.x releases.

**Note on speakers**: brief lists `vidya, anushka, meera, arvind, amol`. Real SDK only has `vidya` and `anushka` (others are `manisha, arya, karun, hitesh, aditya, …`). Default kept at `vidya` per brief.

---

## 2026-05-14 · boto3 pin bump (1.35.0 → 1.35.36)

**Context**: `docs/DAY_1.md` Task 1 locks `boto3==1.35.0` and `aioboto3==13.2.0`. `aioboto3==13.2.0` transitively requires `aiobotocore[boto3]==2.15.2`, which requires `boto3>=1.35.16,<1.35.37`. The set as written is unresolvable — `uv sync` fails immediately.

**Decision**: Bump boto3 to `1.35.36` (top of the compatible range). Keep aioboto3 at the brief's `13.2.0`. Smallest possible deviation from the locked stack.

**Alternatives considered**:
- Bump aioboto3 to a newer line (≥14.x). Unnecessary; current line works.
- Drop boto3 + aioboto3 from Day 1 entirely (they're not used in code until Day 2). Closer to Day 1's spirit but means re-editing pyproject.toml on Day 2; not worth the churn.

**Reversibility**: easy — one-line edit in `pyproject.toml`.

**Revisit when**: aioboto3 line goes EOL or AWS SDK ships a breaking change we want.

---

<!-- Example:

## 2026-05-15 · TTS voice

**Context**: Day 2 acceptance test had Mom listen to both `vidya` and `anushka`.

**Decision**: `anushka` — Mom said it sounds "less robotic."

**Alternatives considered**:
- `vidya` (default in PLAN): functionally identical but Mom found it slightly flat
- `meera`: too formal for the use case

**Reversibility**: easy — one config change in `config.py::TTS_VOICE`

**Revisit when**: Mom's feedback changes, or Bulbul v4 ships with new voices

-->
