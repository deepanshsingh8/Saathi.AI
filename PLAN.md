## Saathi — Technical Architecture & 7-Day Build Plan (v0.1, May 2026)

**For:** Deep (Jaipur) · **End user:** Mom (Hindi/Hinglish speaker, Jaipur, WhatsApp-native) · **Goal:** A WhatsApp voice-note assistant that can reorder medicines (1mg / PharmEasy), order groceries (Blinkit / Zepto / Swiggy Instamart), and pay utility bills (electricity, mobile recharge). All three flows must be reachable end-to-end by Day 7, with **COD-only** for v1 and payments deferred to v2.

This document is opinionated. Where the "obviously cool" path (e.g. WhatsApp Cloud API + Computer Use + agentic UPI) has a 2026 gotcha that will eat your week, that gotcha is called out explicitly. Citations to specific pricing and policy snippets are kept inline so you can verify before you commit.

---

## TL;DR – The shape of the build

- **Messaging layer:** Use the official **WhatsApp Business Cloud API** directly via the Meta Developer dashboard. Skip BSPs (AiSensy / Wati / Interakt). For a single-user, you-and-mom bot, BSPs add cost and friction with zero benefit. Bot is single-tenant: mom's number is hard-coded as the only allowed sender.
- **Voice in/out:** **Sarvam AI Saaras v3** in `codemix` mode for STT, **Sarvam Bulbul v3** for Hindi TTS. Whisper is a fallback. Bhashini is officially "PoC-only" for free tier and not production-fit on day 1.
- **Brain:** **Claude Sonnet 4.6** ($3 / $15 per M tok, 1M context) as the default orchestrator. Haiku 4.5 ($1 / $5) for intent classification and short confirmations. Skip Opus 4.7 for now — Sonnet is within 1.2 points of Opus on SWE-bench, and you don't need that headroom yet.
- **Execution:**
  - **Bill pay** → start with a stubbed/manual flow on Day 1, target the **Cashfree BBPS biller API** or **Eko BBPS API** for v1.1 (requires KYC + onboarding, won't finish in week 1). For week 1, ship a "concierge" mode that pings Deep on Telegram/email for manual pay confirmation, while still acting fully agentic from mom's POV.
  - **Grocery** → **Swiggy Instamart MCP** (mcp.swiggy.com/im) is the cleanest path; it ships COD natively, supports OAuth 2.1 + PKCE, and Swiggy Instamart serves Jaipur. ⚠️ It is whitelist-gated (raise a GitHub issue label `mcp client request`). If access is delayed, fall back to **Playwright + Browserbase** against the Blinkit web checkout.
  - **Medicine** → **Tata 1mg's official merchant API** (`onedoc.1mg.com`) supports COD orders end-to-end via `Create Order API` and is the lowest-friction path *if you can get merchant onboarding*. Backup: Browserbase + Playwright on `pharmeasy.in` (PharmEasy explicitly advertises COD for Jaipur).
- **Hosting:** Single AWS Lightsail instance (Mumbai region, ap-south-1) or **Render Web Service** in Singapore. ~70ms RTT to Anthropic, ~30ms to Bhashini/Sarvam, ~50ms to Meta India edge. Total cost for week 1: under ₹2,000.
- **Storage:** DynamoDB single-table (you already use it) + S3 for media. Don't overthink it. Postgres is overkill for one user.
- **Hard architectural decision:** Deep, you should **build Saathi as your own personal-use first-party assistant, not a chatbot product**, because as of Jan 15, 2026 Meta bans "general-purpose AI assistants" on WhatsApp Business API. Saathi is task-specific (commerce + bill pay), so it sits squarely inside the permitted "structured bots for support, bookings, order tracking, notifications and sales" carve-out — but the framing matters for templates and review.

---

## 1. WhatsApp bot layer — what works in May 2026

### 1.1 WhatsApp Cloud API vs BSPs — what to actually use

Meta sunset the on-premises WhatsApp Business API on **October 23, 2025**. Cloud API is now the only path. For an Indian indie developer building a single-user assistant, **go direct to Meta** for these reasons:

| Path | Setup time | Monthly fixed cost | Per-message | Notes |
|---|---|---|---|---|
| **Meta Cloud API direct** | 1–2 hours | **₹0** | Service replies: free inside 24h window. Utility: ~₹0.115. Marketing: ₹0.8631 (India, Jan 2026 rate). | Self-serve. No verification needed to send to your own test numbers. |
| AiSensy | Half a day | ₹1,500/mo | + ~10% markup | Good UI, useless overhead for 1 user |
| Wati | Half a day | ₹2,499/mo | + markup | Slow broadcast |
| Interakt (Jio/Haptik) | 1 day | ₹2,499/mo | + markup | Stronger D2C/Shopify, irrelevant here |
| Gupshup | Days | ₹4,000+/mo | + markup | Enterprise, overkill |
| Twilio WhatsApp | Half a day | $0 base | $0.005 Twilio + Meta fee per template | Cleanest dev experience, USD billing, ~2× cost of going direct |

**Pricing model (post July 1, 2025):** Meta switched from "conversation pricing" to **per-message** pricing for utility/auth/marketing templates. Service messages (anything you send inside the 24-hour customer service window after mom messages you) remain **free**. For a single user who initiates every interaction, you'll pay essentially zero to Meta for messaging.

The only real friction with going direct: you have to set up webhooks, host the endpoint, and manage your own templates. That's already what Deep wants to do.

### 1.2 Embedded Signup, business verification, GST, DPI

For a personal-use assistant, you do **not** need:

- Meta Business Verification (only needed to unlock green tick, higher message tiers, multiple phone numbers per WABA)
- GSTIN (you're not invoicing customers)
- DPI/DPDP registration (you're the data fiduciary for your own family use, and India's DPDP doesn't have a separate "small developer" registration as of May 2026)

You **do** need:

1. A Meta Developer account (free, ~5 min: developers.facebook.com)
2. A Business Portfolio (auto-created when you make a Meta app)
3. A phone number dedicated to the bot (cannot be the same number mom already has WhatsApp on — see below)
4. A "WhatsApp" use-case app, with the API Setup panel exposing a test recipient list

**Critical phone-number gotcha:** Meta still does not let you run Cloud API on a number that is already registered to the consumer WhatsApp app or WhatsApp Business app, unless you go through **Coexistence**. For week 1, **buy a new prepaid SIM** (a Jio/Airtel prepaid 4G SIM in Jaipur is ₹239, takes a day for OTP capability). Use that number as the Saathi sender. Mom messages *that* number. Her own number stays untouched.

In the Meta App Dashboard's "WhatsApp" > "API Setup" panel, you can add mom's number to the **test recipients** list right away — up to 5 test numbers can receive messages from your unverified app without any review. This is exactly what you want for v1.

### 1.3 The 24-hour window and confirmation flows

This is the single most important policy constraint to design around:

- When mom sends a message to Saathi, a **24-hour customer service window** opens.
- Inside that window, you can send any free-form text, audio, image, interactive button, list, or Flow message — all **free**.
- Outside the window, you can only send **pre-approved templates** (utility/marketing/auth categories).

Order confirmation flows are async: mom says "groceries", Saathi orders, the delivery rider takes 12–25 minutes to reach. If she stays inside the same conversation, you're fine. The risk is the **delivery confirmation** ping that lands 3 hours later when the rider hands the bag over — by then mom may have stopped replying, and the window may have closed.

**Design pattern:** Send order-status pings via a pre-approved **utility template** (e.g., `saathi_order_status` with `{1}=order_type, {2}=status, {3}=eta_minutes`). Utility templates in India cost ~₹0.115 / message, are auto-categorised correctly if you write them transactionally, and don't require marketing opt-in. Anthropic's Claude can draft the template text in Hindi for you. Expect Meta template review to take **24–48 hours**, sometimes longer for the first few — submit on Day 1.

### 1.4 Interactive UI: Buttons, Lists, Flows

You have three interactive primitives available inside the 24h window. Use them aggressively — mom should never have to *type*:

- **Reply buttons** (max 3, ≤20 chars each): Best for yes/no/cancel confirmations. Example: `[हाँ, ऑर्डर करो]` `[नहीं]` `[बदलाव करना है]`
- **List messages** (max 10 rows, grouped in sections): Great for "which medicine?" or "which biller?" picking. Each row has a title + optional short description.
- **WhatsApp Flows**: Full multi-screen forms. Overkill for week 1; consider for v2 (e.g., "Pin code + delivery address change" flow).

For voice-first mom, the optimal pattern is: she sends a **voice note**, Saathi replies with a **short Hindi voice note** summarising the proposed order *plus* a 2-button reply (`हाँ` / `नहीं`). She taps; the order goes. No keyboard, no text reading.

### 1.5 Voice notes — receive, transcribe, respond

Inbound voice notes arrive in your webhook as `type: audio` with a `voice: true` flag and a media ID. Two-step fetch:

```python
# Step 1 — get the media URL (Bearer-authed)
GET https://graph.facebook.com/v22.0/{MEDIA_ID}
Authorization: Bearer {ACCESS_TOKEN}
# returns {"url": "...", "mime_type":"audio/ogg; codecs=opus", ...}

# Step 2 — download the actual bytes (also Bearer-authed)
GET {url_from_step_1}
Authorization: Bearer {ACCESS_TOKEN}
# returns the binary .oga file
```

WhatsApp voice notes are OGG/Opus, mono, 16 kHz. Sarvam's Saaras v3 accepts that natively — no FFmpeg conversion needed. The URL from step 1 is short-lived (~5 minutes) so don't cache it.

Outbound voice: upload an MP3 or OGG to `/PHONE_ID/media` with `messaging_product=whatsapp`, get back a media ID, then send `{"type":"audio", "audio":{"id":"..."}}`. Bulbul outputs 24 kHz MP3 by default — works fine.

### 1.6 Commerce / agent-on-behalf policy — the real fine print

Three policy documents that govern what Saathi can do:

1. **WhatsApp Business Solution Terms** — A "Third Party Service Provider" (which is what Saathi technically is from mom's perspective if you ever scale beyond just her) must "only use the WhatsApp Business Solution and process Business Solution Data on your behalf, pursuant to your instructions and authorization." For week-1 single-user scope, mom is both the principal and the account holder context — you're fine.
2. **General-purpose AI chatbot ban (effective Jan 15, 2026 for all accounts; Oct 15, 2025 for new accounts)** — Meta banned "AI model providers" from distributing open-ended assistants on WhatsApp API. Per Meta's published carve-outs and respond.io's compliance breakdown: **task-specific bots for support, bookings, order tracking, notifications and sales remain allowed**. Saathi is unambiguously in the allowed category — it does ordering and bill pay, not "ask me anything." Frame your template names and app description accordingly ("personal commerce assistant for family"). Do not market it as a "WhatsApp ChatGPT."
3. **Commerce Policy** — Saathi doesn't sell anything; it places orders on third-party platforms on mom's behalf. Meta's Commerce Policy applies only if you use WhatsApp Catalogs or WhatsApp Pay. You're not, so this is moot for v1.

The bigger commerce-policy question is the **ToS of the merchants you automate** — covered in §4 and §9 below.

## 2. Speech: Hindi + Hinglish processing

### 2.1 The stack to actually use

**Recommended pipeline for week 1:**

```
WhatsApp voice note (OGG/Opus, 16 kHz)
      │
      ▼
Sarvam Saaras v3   (mode="codemix", language_code="hi-IN" or "unknown")
      │  → "मम्मी की BP की दवा खत्म हो गयी, please order करवा दो"
      ▼
Claude Sonnet 4.6  (intent + slot extraction + tool routing)
      │
      ▼
Sarvam Bulbul v3   (Hindi voice, "vidya" or "anushka" speaker)
      │  → 24 kHz MP3
      ▼
WhatsApp outbound audio + reply-buttons
```

### 2.2 Why Sarvam over Whisper / Deepgram / Bhashini

| Provider | Hindi/Hinglish ASR | Code-mix | Pricing (May 2026) | Latency | Notes |
|---|---|---|---|---|---|
| **Sarvam Saaras v3** | Excellent — best-in-class for code-mixed Hindi-English | Native, `codemix`/`translit` modes | ₹30 / audio-hour STT ≈ $0.36/hr. ₹15 / 10K chars TTS. ₹1,000 free credits on signup. INR billing, GST invoice. | 600 ms TTS, ~400 ms STT for 10 s clip | Saarika v2.5 is being deprecated → use **`saaras:v3`** with `mode="transcribe"` for Devanagari, `mode="codemix"` if you want the Hindi script + English words preserved as English. |
| OpenAI Whisper API | Good for Hindi alone, poor on code-mixed | Mediocre on Hinglish | $0.006 / minute = $0.36/hr | ~500 ms | USD billing, US data residency. Use as a fallback. |
| Deepgram Nova-3 | Strong English, weaker Hindi | Limited Hindi | $0.0043/min | <300 ms | Best when call is mostly English. Not Saathi's case. |
| AssemblyAI | Strong English, basic Hindi | Limited | $0.37/hr | ~500 ms | Skip. |
| Bhashini (govt) | OK for pure Hindi | Weak on Hinglish | Free tier is **PoC-only** per their own ToS; production access requires written paid-plan request. | High variance (pipeline-discovery model: search → config → compute) | Use only as a backup or for compliance optics. Three-API handshake is friction you don't need in week 1. |
| AI4Bharat IndicConformer / IndicTTS | Excellent open-source quality | Yes | Free if self-hosted, GPU cost ~₹15-25k/yr for a T4 | Depends on infra | Worth considering in v3 once volumes justify it. Not for week 1. |

**Verdict:** Sarvam Saaras v3 + Bulbul v3 for production. Whisper as a 30-line fallback if Sarvam returns 429/5xx.

### 2.3 Cost model for the whole pipeline (per voice exchange)

Assume one round trip = mom's 10-second voice in + Saathi's 8-second voice out + ~2 LLM turns (~3K input tokens, ~500 output):

| Component | Per exchange |
|---|---|
| WhatsApp inbound | ₹0 (service window) |
| WhatsApp outbound (service window) | ₹0 |
| Sarvam STT (10 s → ₹30/hr) | **₹0.083** |
| Claude Sonnet 4.6 (3K in @ $3/M + 500 out @ $15/M) | ($0.009 + $0.0075) × ₹83 ≈ **₹1.37** |
| Sarvam TTS (~250 chars Hindi reply) | ~₹0.40 |
| Whisper fallback (≤1% of traffic) | rounding |
| **Total per voice exchange** | **≈ ₹1.85** |

Mom realistically does 3 exchanges per order × 3 orders/week in week 1 = ~₹17/week. Even at the "200 conversations/day by month 2" scale this is ₹3,700/month. Comfortably in pocket-money territory.

### 2.4 Code starting points

- **Sarvam Python SDK**: `pip install sarvamai` (v4.23.2+). Docs: docs.sarvam.ai. Async support, WebSocket streaming in beta if you want sub-second TTS later.
- **Sarvam STT one-liner** (synchronous, files ≤30 s):
  ```python
  from sarvamai import SarvamAI
  client = SarvamAI(api_subscription_key=os.environ["SARVAM_KEY"])
  with open("voice_note.oga", "rb") as f:
      r = client.speech_to_text.transcribe(
          file=f,
          model="saaras:v3",
          mode="transcribe",          # or "codemix" for Hindi+English mix
          language_code="hi-IN",      # or "unknown" for auto-detect
      )
  print(r.transcript)
  ```
- **Sarvam TTS** with `bulbul:v3`, voice `vidya` (warm female Hindi) or `anushka`. Set `pitch=0`, `pace=1.0`, `loudness=1.2` for an older-listener-friendly cadence.
- **Whisper fallback** via `openai` SDK using `gpt-4o-transcribe` or `whisper-1`.

### 2.5 Latency budget — total round-trip for mom

Target: under 5 seconds from "voice note received" to "voice note sent back" for simple confirmations.

- WhatsApp webhook delivery: ~300 ms India→India
- Media download from Meta: ~400 ms
- Sarvam STT (10 s audio): ~600–900 ms
- Claude Sonnet (one tool call, no browser): 1.5–2.5 s
- Sarvam TTS (~250 chars): ~600 ms
- Outbound media upload + send: ~500 ms
- **Total: ~4.0–5.2 s** — feels conversational for a voice-note style exchange.

Once you involve Browserbase/Playwright for a Blinkit cart, the LLM turn jumps to 30–90 s. **Always send a "मैं देख रही हूँ…" interim voice reply within 3 s**, then send the actual cart summary when ready. Mom will absolutely refresh and resend a voice note if she thinks the bot froze.

## 3. Execution layer — browser, MCP, and API

### 3.1 Reality check on agentic commerce in India (May 2026)

The state of the world right now is messy but workable:

- **Swiggy Builders Club** (launched April 23, 2026, AWS/Bedrock-powered) is the only Indian commerce platform with official, production-grade MCP servers. Three endpoints: `mcp.swiggy.com/food`, `mcp.swiggy.com/im` (Instamart), `mcp.swiggy.com/dineout`. 35 tools across the three. **COD is the supported payment mode for Instamart MCP** out of the gate ("currently supports COD only" per Swiggy's own manifest README). This is a near-perfect fit for Saathi's week-1 constraints.
- **Tata 1mg** has a proper, documented partner/merchant API at `onedoc.1mg.com` covering search, drug detail, OTC detail, prescription upload ("Done in One" flow), create-order, confirm-order, and order-status webhooks. **COD is explicitly the simpler integration path** ("For Cash on Delivery (COD) orders, only the Create Order API is required. No additional transaction handling is necessary.").
- **PharmEasy, Blinkit, Zepto**: no public APIs and no MCP servers as of May 2026. PharmEasy operates in Jaipur with COD; Blinkit operates in Jaipur with COD (with the known caveat that COD reliability is uneven — Blinkit users report cancellations on COD orders); Zepto lists Jaipur in its "Available in 50+ Cities" plate. All three require browser automation or app automation if you want them as agents.
- **Razorpay agentic UPI on Claude** (Feb 20, 2026 pilot announcement with NPCI) does cover Zomato, Swiggy, and **Zepto** — but the rollout is invite-only and Razorpay's `razorpay.com/agentic-payments` is gated to "20+ partners." Not week-1 accessible for an indie. **Defer to v2.**
- **BBPS bill pay APIs** (Cashfree, Razorpay, Eko, ZuelPay) require business onboarding + RBI-driven KYC — minimum 1–3 weeks. **Definitely defer to v2.**

### 3.2 Recommended executor mix for week 1

| Flow | Primary executor | Fallback | COD viable? | Jaipur viable? |
|---|---|---|---|---|
| **Grocery** | Swiggy Instamart MCP (if whitelisted in time) | Playwright + Browserbase on `blinkit.com` web checkout | Yes (Instamart MCP / Blinkit web both) | Yes (Instamart Jaipur live; Blinkit operates in Jaipur per their FAQ) |
| **Medicine** | Tata 1mg Merchant API (if onboarded) | Playwright + Browserbase on `pharmeasy.in` | Yes (1mg COD-only is simplest; PharmEasy COD live in Jaipur) | Yes |
| **Bill pay** | Concierge mode — Saathi parses intent + amount, sends Deep a Telegram/email with payment link; Deep pays, Saathi confirms to mom | Browserbase on each utility's portal (JVVNL for Jaipur electricity, Airtel/Jio for mobile) | N/A (no COD on bills) | Yes |

This is the brutal pragmatic stance. The first two flows can be genuinely agentic on day 7 if Swiggy/1mg whitelist you fast, or genuinely automated via browser if they don't. **Bill pay is the one place where Saathi cheats with a human-in-the-loop for v1** — and that's correct, because the alternatives all require regulatory compliance Deep doesn't have.

### 3.3 Swiggy MCP — exactly how to wire it

```json
// In your Claude Agent SDK config or MCP client
{
  "mcpServers": {
    "swiggy-instamart": { "type": "http", "url": "https://mcp.swiggy.com/im" },
    "swiggy-food":      { "type": "http", "url": "https://mcp.swiggy.com/food" }
  }
}
```

- Auth: **OAuth 2.1 + PKCE**, not a static API key. Either use a framework with native MCP OAuth support (MCP TS/Python SDKs, OpenAI Agents JS, Vercel AI SDK 6, Mastra), or fetch a Bearer token manually via the Authenticate flow and pass `Authorization: Bearer <token>` (works with LangChain MCP adapters, PydanticAI, Anthropic hosted MCP connector).
- Access: invite-led. File a request on the [Swiggy/swiggy-mcp-server-manifest repo](https://github.com/Swiggy/swiggy-mcp-server-manifest) on **Day 1** with the label `mcp client request`. There is a visible queue of pending requests (issues #41–#55 as of early May 2026). Realistic SLA: **3–14 days**, so don't bet the build on it.
- Open warning from Swiggy's own README: *"Be careful as it can place orders on your behalf under COD. Orders placed cannot be cancelled."* — This is exactly your design risk. Always require an explicit voice confirmation from mom before invoking the `place_order` tool.
- **Multi-tool gotcha**: developers report that loading all 35 Swiggy tools into a single Claude context degrades tool selection (the model ignored Instamart and called restaurant search instead). **Split agents per vertical**, or filter tools to ~7 per agent.

### 3.4 Tata 1mg Merchant API — exactly how to wire it

Apply via 1mg's business team (linked from `onedoc.1mg.com`) for a **merchant_id + private key**. Once issued, the COD flow is just:

1. `POST /city-serviceable` → confirm Jaipur is in scope
2. `POST /search` → find "Telma 40 mg" or whatever mom names
3. `GET /drug-detail/{sku}` or `/otc-detail/{sku}` for confirmation
4. `POST /create-order` with `payment_method=COD` and the prescription image (use mom's prior prescription stored in S3)
5. Receive order status updates via your webhook

Auth is JWT; refresh tokens as documented. Realistic onboarding time is also **3–14 days**, gated by their business team availability.

### 3.5 Playwright + Browserbase fallback — what actually works

Because both above APIs are gated, your week-1 deliverable must work even if **neither** whitelist comes through. Plan for browser automation as the default.

**Choice of tool:**

- **Playwright** (Python or Node), driven via Browserbase. Browserbase pricing: free tier is 3 concurrent browsers + 1 browser hour/month; Developer plan $20/mo gets you 100 hours; sessions billed by the minute, extra time ~$0.10–0.12/hr, residential proxy ~$10–12/GB. Has **Stagehand** (AI-augmented natural-language Playwright) which is genuinely useful for sites that change their DOM.
- **Browser Use** (open source, MIT) at ~$0.002/step if you bring your own LLM. Cheaper if you self-host.
- **Anthropic Computer Use** via Claude Sonnet 4.6 (beta header `computer-use-2025-11-24`). State of the art on OSWorld but slow and expensive vs. DOM-level Playwright. Use only as a "vision fallback" when CSS selectors break.

**Session persistence** is the actual hard problem, not page automation:

- Blinkit, Zepto, PharmEasy all use **OTP login** (no password). You'll need to handle OTP delivery to a real phone *the first time*, then persist cookies/local-storage.
- Browserbase has **persistent contexts** — store the auth state from the first manual login, reload it on every subsequent run. Standard Playwright pattern: `context.storage_state(path="mom_blinkit_state.json")` after login, then `browser.new_context(storage_state="mom_blinkit_state.json")` going forward.
- Sessions on these apps last weeks-to-months unless the user logs out elsewhere. Plan to re-OTP every ~30 days (Saathi pings Deep when refresh is needed).
- **For week 1: do the first OTP login manually on Deep's laptop, save state, deploy.** Don't try to automate OTP-from-SMS-to-bot — that's a week's work on its own.

**Anti-bot:** Blinkit and Zepto use Cloudflare; PharmEasy uses standard PerimeterX-style fingerprinting. Browserbase's "Advanced Stealth Mode" (Startup plan, $99/mo) handles 95% of this; for the dev plan, expect occasional CAPTCHA. None of these sites have aggressive anti-automation — they're more worried about price scrapers than COD-ordering family bots.

### 3.6 Bill pay — the honest path

You cannot ship a fully agentic, automated bill-pay flow in 7 days for an indie developer in India. Here's why and what to ship instead:

- **BBPS direct integration** requires RBI-registered NBBL biller onboarding — months, not days.
- **Cashfree BBPS-Biller** says "less than 3 weeks" to connect — still misses the week 1 deadline; and you'd need to register Saathi as a *biller*, which doesn't even fit the model (you're a *payer*).
- **Cashfree / Razorpay / Eko BBPS API** for payment *initiation* (the "I want to pay a bill" side) all require an entity-level merchant agreement and KYC. Not week-1 viable for an unincorporated individual.
- **Browser automation on JVVNL** (Jaipur Vidyut Vitran Nigam Limited, the electricity distco for Jaipur) is possible but they redirect payments to BBPS rails anyway, and the payment step requires a card/UPI/netbanking interaction that Saathi can't autonomously authenticate without storing mom's banking credentials (which you don't want to do).

**Week 1 deliverable for bill pay — "Saathi Concierge mode":**

1. Mom: "बिजली का बिल भर दो"
2. Saathi: Looks up her consumer number from DynamoDB (pre-loaded), opens JVVNL's portal (or scrapes the SMS reminder she forwarded earlier), extracts the **due amount + due date + bill number**, and sends a Hindi voice reply: "तीन हज़ार दो सौ चालीस रुपये का बिल है, 25 तारीख तक भरना है, क्या मैं Deep को भेज दूं भरने के लिए?"
3. On confirmation, Saathi pings Deep via Telegram/email with the JVVNL deep-link, the amount, and the consumer number.
4. Deep pays from his phone in 30 s, replies "done", and Saathi sends mom a confirmation voice note + receipt.

This is **not** a hack — it's the only legally clean path for a single dev in week 1. It also unlocks v2: once you have BBPS or Razorpay agentic UPI access, swap the "ping Deep" step for an API call. Mom's UX doesn't change.

For **mobile recharge**, the same flow works: Saathi confirms operator + circle + amount, Deep recharges via PhonePe in 10 seconds. The only difference is the recharge providers (Jio, Airtel) have public unauthenticated web-checkout that *could* be automated with Browserbase + a stored card, but storing mom's card details is a v2 conversation.

## 4. Orchestration / LLM layer

### 4.1 Model selection

As of May 2026 the Anthropic Claude lineup is:

| Model | Input / Output ($/M tok) | Context | Notable |
|---|---|---|---|
| **Claude Haiku 4.5** | $1.00 / $5.00 | 200K | Cheapest current-gen; 97 tok/s; great for intent/routing |
| **Claude Sonnet 4.6** | $3.00 / $15.00 | 1M | Default for everything; 79.6% SWE-bench (within 1.2 pts of Opus); strong tool use |
| **Claude Opus 4.7** | $5.00 / $25.00 | 1M (300K output in Batch API) | Top-tier reasoning; reserve for *only* the hardest browser-vision cases |

Prompt caching gives **up to 90% savings on cached input** (cache reads bill at $0.30/M on Sonnet). For Saathi this matters because mom's preference profile (her usual medicines, address, biller IDs) will be in every prompt.

**Recommended routing:**

```
Voice transcript
       │
       ▼
   Haiku 4.5  — intent classifier (≤200 in tokens, ≤50 out)
       │       Output JSON: {intent: "grocery|medicine|bill|chitchat", confidence: 0.0-1.0}
       │
       ├── confidence < 0.7 → ask mom a clarifying voice question (Haiku again)
       │
       ▼
   Sonnet 4.6 — orchestrator with tool access
       │       Tools: search_blinkit, get_blinkit_cart, place_blinkit_cod_order,
       │              search_1mg, place_1mg_cod_order, get_jvvnl_bill, notify_deep, etc.
       │
       └── Falls back to Opus 4.7 only if Sonnet fails a tool call ≥2× on the same turn
```

### 4.2 Tool-calling architecture

Use the **Claude Agent SDK** (`pip install claude-agent-sdk`, or TypeScript). It gives you:
- A built-in agent loop (gather context → take action → verify) you don't have to write.
- Native MCP server support — drop the Swiggy MCP in `mcp_servers={"swiggy-im":{"url":"https://mcp.swiggy.com/im"}}` and Claude can call those tools directly.
- Allow-listing of tools per agent run (`allowed_tools=["mcp__swiggy-im__*", "place_1mg_order", ...]`) to avoid the 35-tool attention-degradation problem.
- A clean subagent pattern: a per-intent subagent (Grocery subagent, Medicine subagent, Bill subagent) each with a narrow tool list.

The Anthropic launch announcement (May 13, 2026) explicitly recommends this "agent loop with verification" pattern; their reference quickstarts include a working `computer-use` demo and a clean tool-calling sample.

```python
from claude_agent_sdk import query, ClaudeAgentOptions
import asyncio

GROCERY_SYSTEM = """You are Saathi's grocery sub-agent. The user is Mom in Jaipur 
(pin 302017). She speaks Hindi/Hinglish. Default to Swiggy Instamart; fall back to 
Blinkit via browser if Instamart is unavailable. ALWAYS confirm cart with Mom in 
Hindi before placing. Payment is COD only. Address is saved in user_profile."""

async def grocery_turn(transcript: str, user_profile: dict):
    async for msg in query(
        prompt=transcript,
        options=ClaudeAgentOptions(
            model="claude-sonnet-4-6",
            system_prompt=GROCERY_SYSTEM + f"\n\nUser profile: {user_profile}",
            mcp_servers={"swiggy_im": {"type":"http", "url":"https://mcp.swiggy.com/im"}},
            allowed_tools=["mcp__swiggy_im__*", "send_whatsapp_audio", "save_basket"],
            max_turns=12,
        ),
    ):
        if hasattr(msg, "result"):
            return msg.result
```

### 4.3 Hinglish prompting patterns

A few patterns that work well in production Hindi/Hinglish bots:

- **Always echo back the parsed intent in the user's language** before acting. *"मम्मी, मैंने समझा: टेलमा 40 की एक स्ट्रिप, COD पर, घर के पते पर — सही?"*
- **Numbers are the hardest part**. Sarvam's `transcribe` mode normalises Hindi number words to digits (`दो हज़ार रुपये` → `₹2000`). Verify the amount before any payment-adjacent action. For amounts ≥ ₹1000, always **read the digits out loud one by one** in the confirmation voice note.
- **Medicine names are routinely mispronounced or vague**. *"वो जो पीली गोली है"* ("that yellow pill") will happen weekly. Maintain a `mom_medicine_dictionary` in DynamoDB: `{user_term: canonical_sku, brand, dosage, last_ordered}`. Prepend this to Claude's system prompt every turn.
- **Refuse gracefully in Hindi**. If Claude isn't sure, the reply should be: *"मम्मी, मुझे थोड़ा confusion है — क्या आप एक बार और बोलेंगी?"* — not "I'm sorry, I didn't understand."
- **Never abbreviate ₹ in TTS text**. Sarvam Bulbul says "rupayye" correctly only if you write the word out: `₹3,240` → `तीन हज़ार दो सौ चालीस रुपये`.

### 4.4 Context / "usual basket" memory

Single-user means you can be ruthlessly stateful. DynamoDB single table (`pk=mom`, `sk=basket#<timestamp>` for orders, `sk=med#<sku>` for medicines, `sk=profile` for address+billers). On every conversation turn:

1. Load `pk=mom, sk=profile` (1 read).
2. Load last 3 orders matching the detected intent (1 query).
3. Inject as a JSON block in the Sonnet system prompt with prompt caching enabled (`cache_control: {"type":"ephemeral"}` on that block). 90% input-token discount after first call.
4. After successful order, write back `sk=basket#<ts>` with item list, COD amount, status.

You don't need a vector DB. You don't need RAG. Mom orders 8 distinct items, 12 medicines and 3 billers total. Just store the dict.

## 5. Hosting / infrastructure

### 5.1 The simplest deployment that works

You want one box, one webhook URL, one DB, one Python process. Two candidates:

| Option | Cost (month) | Pros | Cons |
|---|---|---|---|
| **AWS Lightsail Mumbai (ap-south-1)** — 2 vCPU, 2 GB, 60 GB SSD, 3 TB transfer | ₹830 ($10) | Same region as DynamoDB, lowest latency to Sarvam, deep already on AWS, easy to migrate to ECS later | You manage Nginx, certbot, systemd |
| **Render** (Singapore region) Standard Web Service | $7 | Zero ops, auto-deploy from GitHub, HTTPS free | ~60 ms further from Sarvam/Meta India edge |
| Fly.io (Mumbai `bom` region) | $3 base | Auto-restart, good multi-region story | Smaller free tier than before |
| Railway | $5+ usage | Slick DX | No India region |

**Recommendation:** Lightsail Mumbai. Deep already has AWS muscle memory, DynamoDB is right there in the same VPC, and you can attach an Elastic IP so the webhook URL never changes. CloudFront in front for HTTPS is a 10-minute setup but Lightsail's bundled Let's Encrypt also works.

### 5.2 Latency from a Mumbai box

Approximate RTTs measured from `ap-south-1` to each upstream:

| Upstream | Region/edge | RTT |
|---|---|---|
| WhatsApp Cloud API webhook receive (inbound) | Meta India edge | ~30–60 ms |
| WhatsApp Cloud API send | Meta India edge | ~30–60 ms |
| Sarvam AI | Mumbai-hosted | ~20–40 ms |
| Bhashini (if used) | Bengaluru | ~40–60 ms |
| Anthropic API (`api.anthropic.com`) | US-East default; ~250 ms India→US | **~220–280 ms** |
| Anthropic via AWS Bedrock `ap-south-1` | Mumbai | **~30–60 ms** (Bedrock Claude is generally available in ap-south-1 since 2025; Sonnet 4.6 + Opus 4.7 are live there as of Q2 2026) |
| DynamoDB `ap-south-1` | Mumbai | <10 ms |
| Browserbase | US-West / EU | ~250–400 ms control plane; the *target site* RTT is what matters and Blinkit/Zepto live in India |

**Optimisation that matters:** Route Claude calls through **Bedrock `ap-south-1`** rather than `api.anthropic.com`. You'll save ~200 ms per LLM turn. Set `CLAUDE_CODE_USE_BEDROCK=1` for Agent SDK, or use the `boto3` Bedrock client directly. Anthropic bills CCU (Claude Consumption Units) at $0.01/CCU on AWS Marketplace; pricing translates 1:1 from token rates, no Bedrock surcharge.

### 5.3 Cost projection

Week 1 (you + mom testing, ~20 turns/day):

| Line | Daily | Monthly |
|---|---|---|
| Lightsail Mumbai | ₹28 | ₹830 |
| Claude (Sonnet via Bedrock, 20 turns × ~3K in / 500 out, with caching) | ~₹35 | ₹1,000 |
| Sarvam STT+TTS | ~₹15 | ₹450 |
| Browserbase Developer plan | — | ₹1,660 ($20) |
| DynamoDB (on-demand, microscopic for 1 user) | <₹1 | ~₹30 |
| WhatsApp Cloud API | ₹0 | ₹0 (all in service window) |
| **Total month 1** | | **~₹4,000** |

Month 2 (~200 turns/day across a small family pilot):

| Line | Monthly |
|---|---|
| Lightsail | ₹830 |
| Claude (10× volume, prompt caching pays off harder) | ~₹6,000 |
| Sarvam | ~₹2,500 |
| Browserbase Startup plan | ~₹8,200 ($99) |
| WhatsApp (a few utility templates per day per user) | ~₹500 |
| DynamoDB | ~₹100 |
| **Total month 2** | **~₹18,000** |

Comfortably below "weekend project that became an obsession" budget.

### 5.4 Webhook setup

WhatsApp Cloud API webhooks are dumb — they POST JSON to your HTTPS URL and expect 200 within 20 s. Standard pattern:

```
HTTPS POST /webhook  ──► FastAPI (ack 200 immediately)
                              │
                              └──► enqueue to SQS / Redis Stream
                                            │
                                            └──► worker(s) do the actual STT + LLM + send-back
```

Don't try to do everything inline. The 20 s timeout is fine for ack-then-process. The send-back goes via a separate POST to `graph.facebook.com/v22.0/{PHONE_ID}/messages` and is independent of the webhook response cycle.

A bare-bones `webhook.py`:

```python
from fastapi import FastAPI, Request, BackgroundTasks
import boto3, hmac, hashlib, os

app = FastAPI()
sqs = boto3.client("sqs", region_name="ap-south-1")
QUEUE = os.environ["WHATSAPP_QUEUE_URL"]

@app.get("/webhook")
def verify(hub_mode: str, hub_verify_token: str, hub_challenge: str):
    if hub_verify_token == os.environ["WA_VERIFY_TOKEN"]:
        return int(hub_challenge)
    return {"error": "bad token"}

@app.post("/webhook")
async def webhook(req: Request, bg: BackgroundTasks):
    body = await req.body()
    # X-Hub-Signature-256 validation
    sig = req.headers.get("x-hub-signature-256","").removeprefix("sha256=")
    expected = hmac.new(os.environ["WA_APP_SECRET"].encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return {"error":"bad signature"}, 401
    sqs.send_message(QueueUrl=QUEUE, MessageBody=body.decode())
    return {"ok": True}
```

### 5.5 Persistent storage layout (DynamoDB single table)

```
PK              SK                    Attributes
mom             profile               { name, address, pin, billers:{electricity:CONSUMER_NUM,
                                        mobile:NUMBER}, meds:[{sku,brand,dose,last}], 
                                        prescriptions:[s3_url] }
mom             session#<conv_id>     { last_intent, slots, opened_at, expires_at }
mom             order#<ts>            { source, items, amount, status, eta, cod }
mom             med#<sku>             { brand, dose, frequency_days, last_ordered }
mom             prescription#<ts>     { s3_url, doctor, expiry, items }
```

Single GSI on `(SK, PK)` if you ever need cross-user queries; for now you won't. TTL attribute on session items, expire after 24h.

## 6. The 7-day build plan

### Day 1 — Accounts, plumbing, and the long-poll requests

**Goal: by EOD, you can echo a voice note back to yourself on WhatsApp.**

Morning (3 hours):
1. **Buy the second SIM** in your name (Jio/Airtel prepaid, ₹239, 30 min at a store). Activate it in a spare handset or eSIM.
2. **Meta Developer signup**: developers.facebook.com → create app → "Business" → add "WhatsApp" product → API Setup. Add the new number, do the OTP verification, add mom's number as a test recipient.
3. **Anthropic Console**: console.anthropic.com → fund $20 → grab API key. Also enable Bedrock Claude in your AWS console (ap-south-1, request model access for `claude-sonnet-4-6` and `claude-haiku-4-5` — instant for existing AWS accounts).
4. **Sarvam AI**: sarvam.ai → signup, claim ₹1,000 free credit, grab API key. Test Saaras v3 in their playground with a recorded Hindi voice note from your own phone.
5. **Browserbase**: browserbase.com → free tier first, you'll upgrade to Developer plan on Day 4 once you confirm you need it.

Afternoon (4 hours):
6. **Spin up Lightsail Mumbai** instance + static IP. Install Python 3.12, Caddy (auto-HTTPS), and your usual systemd/uv toolchain.
7. **Domain**: point a subdomain like `saathi.yourdomain.in` to the static IP. Caddy gets HTTPS in 30 s.
8. **Webhook skeleton**: deploy the FastAPI skeleton above. Configure the WhatsApp webhook in Meta dashboard, verify token, subscribe to `messages` field.
9. **Smoke test**: send a text "hello" from mom's number to the bot number. Confirm webhook receives the JSON and your code can POST back `नमस्ते मम्मी` to her.

Evening (1 hour, async / batched):
10. **File access requests in parallel**:
    - Open a GitHub issue on `Swiggy/swiggy-mcp-server-manifest` with label `mcp client request`, brief description of your use case, your callback URL.
    - Email Tata 1mg business (form on `1mg.com/for-business` or via `onedoc.1mg.com` contact) for merchant API access.
    - Submit your first **utility template** to Meta for review: `saathi_order_status` with body *"नमस्ते {{1}}, आपका {{2}} ऑर्डर {{3}} है। समय: {{4}}"*. Expect 24–48 h review.

**Day 1 done = you can text-message mom from the bot.**

---

### Day 2 — Voice in, voice out, basic state

**Goal: by EOD, mom can send a voice note and get a Hindi voice reply.**

1. Implement **inbound voice handling**: webhook detects `type=audio` → fetch media URL → download → upload to S3 (`mom/voice/<ts>.oga`).
2. Wire **Sarvam Saaras v3** STT call: ≤30 s sync; for longer, Sarvam batch.
3. Wire **Sarvam Bulbul v3** TTS: take a Hindi string, generate MP3, save to S3, upload to Meta media endpoint, send as audio message.
4. Add **Claude Haiku 4.5 intent classifier** (system prompt: classify the transcript into `grocery|medicine|bill|chitchat|unknown` and extract slots).
5. Stand up **DynamoDB table** `saathi`, seed mom's profile, address (pin 302017 or wherever in Jaipur), and electricity consumer number from her last JVVNL bill.
6. **End-to-end echo test**: mom says "नमस्ते Saathi", bot responds with synthesised "नमस्ते मम्मी, मैं Saathi बोल रही हूँ, बताइए क्या चाहिए?"

**Day 2 done = full voice loop works on canned responses.**

---

### Day 3 — One real flow: pick the easiest

Of the three, **medicine reorder via 1mg + Browserbase fallback** is the fastest to ship because:
- The most stable web flow (medicine catalog doesn't change daily).
- COD is well-supported and there's no SKU ambiguity for prescription refills (mom has a saved prescription).
- 1mg's web checkout has predictable selectors and zero anti-bot fight.

Day 3 plan:
1. Use Browserbase + Playwright in Python. Manually OTP-login as mom to `1mg.com` once, save `storage_state.json` to S3.
2. Write three Playwright functions: `search_drug(name)`, `add_to_cart(sku, qty)`, `checkout_cod(address_id)`.
3. Wire them as **Anthropic-style tool definitions** on a `MedicineAgent` (Sonnet 4.6, Agent SDK).
4. End-to-end voice flow: *"टेलमा 40 खत्म हो गयी, please order करवा दो"* → Saathi confirms in voice → mom taps "हाँ" reply button → Playwright places COD order → Saathi voice-confirms with order ID and ETA.
5. **First real test with mom in the room. Get her actually doing the voice note.**

**Day 3 done = one fully working flow. If it doesn't work today, the rest of the week is at risk — descope ruthlessly.**

---

### Day 4 — Second flow: groceries

1. If Swiggy MCP whitelist arrived: wire `mcp.swiggy.com/im` per §3.3 above, OAuth flow once for mom, persist the token. Build a `GrocerySubAgent` with only the 7-ish Instamart tools (cart, search, address, place_order, etc.). **Don't combine with food.**
2. If MCP didn't arrive yet (likely): Playwright on Blinkit. Same pattern as 1mg. Save storage_state. Three tools: `search_blinkit`, `add_to_cart`, `checkout_cod`.
3. Add a `usual_basket` concept: pre-load mom's 8–10 staple items into DynamoDB. *"रोज़ का सामान"* triggers the whole basket; she can edit by voice.
4. Test full flow with mom.

**Day 4 done = two flows.**

---

### Day 5 — Third flow: concierge bill pay

1. Build a JVVNL bill-fetch using Playwright (no payment, just **fetch outstanding amount** for her consumer number — that's a 2-page browser flow on `bill.jvvnl.com`).
2. Build the **"notify Deep" tool** — sends you a Telegram message with the bill link + amount + mom's confirmation token. Mom never sees this part.
3. Build the **"Deep confirmed" callback** — when you reply `paid` to the Telegram bot, Saathi sends mom a confirmation voice note + screenshots the JVVNL receipt and forwards as an image.
4. **Mobile recharge** is even simpler: Saathi only needs to know operator + amount; recharge gets done by Deep on his PhonePe in 10 s. Use the same concierge tool.

**Day 5 done = all three flows reachable end-to-end.**

---

### Day 6 — Polish and the "मम्मी UX" pass

This is where the bot becomes *usable*, not just *working*.

1. **Always-on interim ack**: every voice note gets a 1-second "ठीक है मम्मी, देख रही हूँ" reply within 2 seconds. Then the real reply lands when ready. Without this, mom will re-send 3 times.
2. **Two-button confirmations** on every spend ≥ ₹100. Read the rupee amount **digit by digit** in the voice. ("तीन… दो… चार… शून्य रुपये")
3. **Failure voice responses in Hindi**, never English. Pre-write 8 of them: "मम्मी, अभी कुछ technical दिक्कत है, थोड़ी देर बाद try करूंगी," etc.
4. **The "रोको" command** — if mom says "रुको" / "रद्द करो" / "cancel" at any point during the agent loop, Sonnet must abort the next tool call. Implement via a server-side flag + an agent hook.
5. Add an explicit `notify_deep(severity, message)` tool so the bot escalates anything it's <80% confident about, instead of guessing.

---

### Day 7 — Mom uses it for real; fix what breaks

1. Sit with mom for 60 min in the morning. Have her order one thing, pay one bill, ask one chitchat question that's deliberately ambiguous.
2. **Log everything.** Every transcript, every tool call, every response. CloudWatch + DDB.
3. Fix the top 3 failures (it will be name pronunciation, button mis-taps, or Sonnet placing the wrong cart). Ship within hours.
4. Leave mom alone for the afternoon. Check the log at dinner. Fix one more thing.
5. v1 = shipped.

---

### What to cut if you fall behind

In strict descope order, cut:

1. **WhatsApp Flows / fancy interactive UI** — buttons are enough.
2. **Mobile recharge** — bill pay alone covers the "ungated" use case.
3. **Browser fallback for Swiggy** — if MCP doesn't whitelist by Day 4, ship grocery via Blinkit Playwright only. Skip Swiggy until v1.1.
4. **Bill pay** — if Day 5 implodes, ship Day 7 with only medicine + grocery, and *tell mom* the bill pay is coming next week. Two working flows on Day 7 is far better than three broken ones.

### Realistic risks

- **Swiggy MCP whitelist never arrives within the week.** Probability: 40%. Mitigation: ship Blinkit-Playwright path on Day 4.
- **1mg merchant API onboarding takes 2 weeks.** Probability: 70%. Mitigation: Day 3 ships on Playwright; swap to API in v1.2.
- **Sarvam Bulbul mispronouncing brand names.** Probability: 100% for at least 5 of mom's medicines. Mitigation: a `pronunciation_overrides` dict — write `Telma` as `टेल्मा` for the TTS input.
- **PharmEasy/Blinkit pushes a CAPTCHA**. Probability: 20% per week. Mitigation: Browserbase Advanced Stealth + an alert that pings Deep to manually solve once, after which the cookie holds for weeks.
- **WhatsApp template rejected**. Probability: 25% on first submission for Hindi templates. Mitigation: submit two variants on Day 1 (`saathi_order_status` and `saathi_order_status_v2`) so at least one survives.
- **Mom finds the voice replies "creepy" or too slow.** Probability: small but real. Mitigation: Day 7 explicitly ask her, switch from `vidya` to `anushka` if she prefers, or even fall back to text-only.

## 7. Architecture diagram (text)

### 7.1 Data flow (ASCII; render in any markdown viewer)

```
                            ┌───────────────────────────────┐
                            │  Mom (WhatsApp on her phone)  │
                            └───────────────┬───────────────┘
                                            │ voice note (OGG/Opus, 16 kHz)
                                            ▼
                            ┌───────────────────────────────┐
                            │  WhatsApp Cloud API (Meta)    │
                            │  service window: 24 h         │
                            └───────────────┬───────────────┘
                                            │ webhook POST
                                            ▼
        ┌──────────────────────────────────────────────────────────────┐
        │     FastAPI on Lightsail Mumbai  (saathi.deep.dev)           │
        │     - HMAC signature verify                                  │
        │     - enqueue to SQS, return 200 immediately                 │
        └──────────────────────────┬───────────────────────────────────┘
                                   │
                                   ▼
        ┌──────────────────────────────────────────────────────────────┐
        │     Worker process (Python, asyncio)                         │
        │                                                              │
        │     1. fetch_media() ──► WhatsApp media endpoint             │
        │                          (Bearer auth, 5-min URL)            │
        │     2. S3 put_object("mom/voice/<ts>.oga")                   │
        │     3. Sarvam Saaras v3  → transcript (Hindi script)         │
        │     4. Haiku 4.5 ─→ intent classifier                        │
        │     5. Load profile + recent context from DynamoDB           │
        │     6. Sonnet 4.6 (via Bedrock ap-south-1)  ──┐              │
        │            with tools:                       │              │
        │            ─ MCP swiggy_im (if whitelisted)  │              │
        │            ─ Playwright/Browserbase tools    │              │
        │            ─ 1mg merchant API client         │              │
        │            ─ notify_deep (Telegram bot)      │              │
        │            ─ send_whatsapp_audio/text/btn    │              │
        │            ─ save_basket, write_order        │              │
        │     7. Tool execution loop (max 12 turns)    │              │
        │     8. Sarvam Bulbul v3  ─► MP3 reply        │              │
        │     9. Upload to WhatsApp media, send audio  │              │
        │    10. Persist transcript+order to DynamoDB  │              │
        └─────────────────────┬──────────────────┬────┴───────────────┘
                              │                  │
                              ▼                  ▼
                  ┌───────────────────┐  ┌─────────────────────────────┐
                  │  Executors        │  │   State                     │
                  │                   │  │   - DynamoDB: profile,      │
                  │  ▷ Swiggy MCP HTTP│  │     sessions, orders, meds  │
                  │  ▷ Browserbase    │  │   - S3:  voice notes,       │
                  │    + Playwright   │  │     prescription images,    │
                  │    (Blinkit, 1mg, │  │     bill PDFs               │
                  │     PharmEasy,    │  │   - SecretsManager: tokens, │
                  │     JVVNL portal) │  │     saved storage_state JSON│
                  │  ▷ 1mg API client │  │     for Playwright contexts │
                  │  ▷ Telegram bot   │  │                             │
                  │    (concierge)    │  │                             │
                  └─────────┬─────────┘  └─────────────────────────────┘
                            │
                            ▼
              ┌────────────────────────────┐    ┌──────────────────────┐
              │  Real third parties        │    │  Deep (on Telegram)  │
              │  Blinkit / Zepto web       │    │  receives bill-pay   │
              │  Tata 1mg / PharmEasy      │    │  concierge requests, │
              │  Swiggy Instamart          │    │  taps "paid"         │
              │  JVVNL bill portal         │    │                      │
              └────────────────────────────┘    └──────────────────────┘
```

### 7.2 Failure modes and fallbacks

| Failure | Detection | Fallback |
|---|---|---|
| Sarvam STT 429/5xx | HTTP code | Whisper API (OpenAI) as a one-line backup |
| Sarvam TTS 429 | HTTP code | Send a *text* reply instead of voice; log for review |
| WhatsApp media URL expired (>5 min) | 401 from Meta | Skip, ask mom to resend |
| Sonnet returns no tool call after 3 turns | turn counter | Send mom: *"मुझे थोड़ी मदद चाहिए, एक minute"* and ping Deep via Telegram with the transcript |
| Playwright selector miss | exception | Retry once with Stagehand AI selector resolution; if still fails, ping Deep |
| 1mg/Blinkit OTP wall (cookie expired) | redirect to login | Mark account as "needs refresh", concierge mode kicks in, alert Deep to re-OTP at his next free time |
| Swiggy MCP OAuth token expired | 401 | Refresh via PKCE; if refresh fails, switch to Blinkit Playwright for that order |
| Mom said "रोको" mid-flow | server flag (`session#x.aborted=true`) | Abort next tool call, voice-confirm cancellation |
| WhatsApp template rejected for a status ping | webhook status `template_rejected` | Use a generic pre-approved `saathi_status_v2`; fall back to text-in-window if she's still in the 24h window |
| Order placed but wrong items | mom complaints | Saathi can't undo a Blinkit COD order via web; ping Deep, who calls support |
| LLM hallucinated a price | mismatch with cart total | Always read **the actual cart total returned by the executor**, never the LLM's number; enforce this as a tool-output contract |

### 7.3 Where state is stored

- **Conversation state** (intent, slots, pending confirmations): DynamoDB `pk=mom, sk=session#<conv_id>` with 24-h TTL.
- **Persistent profile** (address, billers, family members, prescriptions): DynamoDB `pk=mom, sk=profile`.
- **Order history**: DynamoDB `pk=mom, sk=order#<ts>`.
- **Voice files, prescriptions, receipts**: S3 with KMS encryption.
- **OAuth tokens, session cookies, storage_state JSON for Playwright**: AWS Secrets Manager (per-merchant, per-user).
- **API keys**: Secrets Manager.
- **Logs**: CloudWatch with 30-day retention.

## 8. Indian e-commerce reality check

### 8.1 COD on Blinkit / Zepto / Instamart web

- **Blinkit web checkout**: COD is offered for orders **above ₹100**. Known reliability issue — some users report COD orders cancelled or undelivered (Blinkit's own communities document this). Mitigation: in Saathi, default to UPI/card *eventually* (v2) and keep COD for testing only. For week 1 it's the only option, accept the ~5% failure rate.
- **Zepto**: COD listed as a payment option on the app and on the web (Google Play listing lists "Cash on Delivery (COD), UPI, cards, wallets, netbanking"). Zepto explicitly lists **Jaipur** as a covered city in its app listing.
- **Swiggy Instamart MCP**: confirmed COD-only at launch ("currently supports COD only") per the Swiggy MCP manifest README. This is actually a *feature* for your week-1 constraint.

### 8.2 COD on 1mg / PharmEasy

- **PharmEasy**: explicit COD on prescription medicines in Jaipur. Their Jaipur city page confirms "you can also choose to pay cash on delivery." Delivery in 24–48 h standard; same-day "express" available for select PIN codes and SKUs.
- **Tata 1mg merchant API**: *"For Cash on Delivery (COD) orders, only the Create Order API is required. No additional transaction handling is necessary."* Cleanest possible integration.
- Both require a valid **doctor's prescription image** for scheduled drugs (most BP/diabetes/cholesterol meds qualify). Pre-upload one of mom's recent prescriptions to S3 and pass its URL in the create-order payload. PharmEasy and 1mg both accept image upload; both also accept the same prescription for multiple refills inside ~6 months.

### 8.3 Jaipur PIN-code coverage (verified, May 2026)

| Service | Jaipur | Notes |
|---|---|---|
| Blinkit | ✅ Yes (city-wide; named in their official 20+ cities list) | Live since 2023, dense in Vaishali Nagar / C-Scheme / Mansarovar |
| Zepto | ✅ Yes (Tier-2 expansion: Jaipur, Ahmedabad, Lucknow) | Coverage thinner than metros; some southern PINs not covered |
| Swiggy Instamart | ✅ Yes | Strongest in Malviya Nagar / C-Scheme / Vaishali |
| BigBasket | ✅ Yes | Slot-based, next-day mostly |
| PharmEasy | ✅ Yes (city page exists; same-day "express" for selected PINs) | 24–48 h standard |
| Tata 1mg | ✅ Yes (delivers in 1,200+ cities, 19,000+ PINs incl. Jaipur) | |
| JVVNL (electricity) | ✅ Native | Online portal `bill.jvvnl.com`, also accepts BBPS |

**One Jaipur-specific quirk**: Mansarovar, Pratap Nagar (southern Jaipur) sometimes shows as "out of zone" on Blinkit/Zepto during peak hours. Have Saathi check coverage with a `pin_serviceable` call before promising mom an ETA.

### 8.4 WhatsApp Business verification (DPI, GSTIN) — actual requirements

For a single-user personal-use bot:

- **GSTIN**: **not required**. Meta's Cloud API onboarding asks for "legal business name" but accepts the developer's own legal name without a GSTIN. Verification (the green tick) needs business documents, but you don't need verification for week 1.
- **DPI / DPDP Act 2023 compliance**: India's Digital Personal Data Protection Act is in force but the operational rules (registration of fiduciaries, etc.) are being phased in through 2026. As a developer storing only your own family's data and not offering Saathi as a service to strangers, you are a "data fiduciary" with self-regulating obligations — keep voice files encrypted at rest, have a written intent (a Notion page is fine for v1), allow mom to ask for deletion, and you're effectively compliant.
- **Phone-number ownership**: Meta requires you to own/control the number you register. A prepaid SIM in your name is fine. Cloud API does **not** accept VoIP numbers (Google Voice, Twilio non-WhatsApp numbers) reliably.
- **Indian INR billing**: Meta added local INR billing for India in January 2026 — useful for accounting, but at zero billable volume in service window it doesn't matter.

## 9. Legal / policy considerations

This is the section where being honest with Deep matters most. Saathi for *just mom* is fine. Saathi for paying customers is not, without incorporating and getting the right licences.

### 9.1 Can an unincorporated individual run an order-placing bot for their own family?

**Yes, for personal use.** You're not a "platform" in any regulatory sense. You're a tool that authenticates to commerce sites *as mom* (using her actual account, with her standing consent). This is functionally identical to mom asking you to "order my BP medicine from 1mg, here's my login" — except automated. The same analysis applies that applies to a personal shopping script you'd write for yourself.

**Caveats even for personal use:**

- Maintain a one-page **family consent document**, signed/voice-recorded by mom, stating she authorises Deep and Saathi to place orders on her behalf, with monetary limits. Practical, not legal, but covers you if 1mg ever asks "who placed this order?".
- Don't share Saathi with anyone outside the immediate family **without** restructuring as a company.
- Mom's account: keep it as *her* account. Saathi automates her actions; it doesn't impersonate her to fraudulently *create* accounts.

### 9.2 Terms of Service of the executors

| Merchant | Automated access rules (May 2026) |
|---|---|
| **Swiggy (Food + Instamart + Dineout)** | Explicitly invites developers via Builders Club. MCP servers are an *official* automation surface. Use is bound by Builders Club rules + Swiggy ToS. **Fully sanctioned** if you're whitelisted. |
| **Tata 1mg (merchant API)** | Has a "Merchant Integration" program. Onboarded merchants can place orders on behalf of their users. The merchant has compliance obligations (prescription validity, no controlled substances, etc.). **Fully sanctioned** once you're onboarded. |
| **PharmEasy** | No public API, ToS prohibits "automated means including bots, scripts, or scraping tools" to "create accounts, place orders, or extract data." Browser automation as *the account holder herself* is a grey area; using her saved login, with her consent, for her own orders is the most defensible position. **Don't scale this. Don't share it. Don't market it.** |
| **Blinkit (Zomato)** | Same posture as PharmEasy. ToS prohibits automation. Same defence (acting as the account holder, with consent, for her own household orders) applies. **Same warning: do not commercialise.** |
| **Zepto** | Same as Blinkit. |
| **JVVNL portal** | Public utility portal, accessing it as the account holder is fine. No anti-automation clause that would catch a personal script. |

The honest summary: **Swiggy and 1mg are green-lit by their own published developer programs. Blinkit, Zepto and PharmEasy are tolerated for personal use but explicitly prohibited for commercial automation.** Build Saathi against the green-lit ones where you can; use browser automation on the others *only as long as it's mom*.

### 9.3 When you must incorporate

You cross the line from "personal tool" to "regulated product" the moment any of these happen:

- You let a third person (uncle, friend's parent) use Saathi. Now it's a service.
- You charge anything (subscription, per-order fee). Now it's a business.
- You hold or move other people's funds (UPI mandates, wallet balances, prepaid loads). Now you need RBI's good books.
- You enable payment without explicit per-transaction user authentication beyond the initial consent. Now you're inside RBI's "agentic payments" / e-mandate framework.

The moment any of those happens, the minimum corporate hygiene is:

1. **Private Limited Company** (Pvt Ltd) — ~₹10K–15K via Razorpay Rize or LegalRaasta; 7–14 days.
2. **GSTIN** — once turnover crosses ₹20L, but earlier voluntary registration helps when integrating with Sarvam/Anthropic for input tax credit.
3. **DPDP fiduciary registration** — once notified by MeitY, expected late 2026.
4. **PCI-DSS** if you ever store card data (don't; let Razorpay tokenize).
5. **For UPI agentic payments**: partner with a TPAP (Razorpay, PhonePe) and live under their authorisation. Razorpay's agentic UPI program is the cleanest 2026 path; sign up at `razorpay.com/agentic-payments`.
6. **For BBPS bill pay**: integrate via a Cashfree / Razorpay / Eko biller-side or BBPS BBPOU partner — *they* hold the RBI authorisation, you ride on it.

### 9.4 WhatsApp policy on third-party-on-behalf commerce

The Jan 15, 2026 "AI-Assisted Business Messaging Guidelines" require, for commercial AI bots:

- **Disclose AI use** in the first message of any session.
- **Provide a human handoff path** ("मम्मी, अगर आप Deep से बात करना चाहें, 'Deep को बुलाओ' बोलिए") — easy to implement.
- **No medical/legal/financial advice without disclaimers**. Reordering BP medication is fine; Saathi diagnosing BP is not.
- **General-purpose AI assistants are banned**. Saathi is a task-specific commerce bot — explicitly allowed.

For personal use these are sensible defaults anyway, and you'd want them in the design even if Meta didn't require them. Implement the AI disclosure as a one-time greeting message the first time mom uses the bot, plus a `/help` style command.

## 10. What's explicitly deferred to v2 (and why)

Write these on a sticky note. Don't let scope creep eat the week.

### Explicitly deferred from v1

1. **Razorpay agentic UPI** / NPCI Reserve Pay / SBMD mandates. Mom will pay COD on Day 7. This is the single biggest constraint that *also* keeps you out of every payment regulator's purview while you de-risk the rest.
2. **Multi-user support.** v1 hardcodes mom's phone number as the only allowed sender. Reject silently from any other number. No "tenant" model, no auth, no rate limiting per user.
3. **Family-shared accounts** (adult-child sets up, parent uses). This is a great v3 idea, but it requires a sponsor-onboarding flow, role-based permissions, and likely a small web app. Out of scope.
4. **Pre-cached preferences and learned baskets**. v1 has a *hand-curated* basket in DynamoDB (Deep types it in). v2 will *learn* by observing 30 days of orders. Don't build the learning loop until you have the orders.
5. **BBPS direct integration** for autonomous bill pay. v1 uses Saathi-Concierge mode (Deep is the human in the loop). v2 once Cashfree/Eko/Razorpay BBPS onboarding completes.
6. **Mobile recharge automation** beyond concierge. Cards/UPI for recharge requires storing payment instruments — defer.
7. **Swiggy Food / Dineout** integration. Even if MCP whitelist arrives, focus only on **Instamart** in week 1. Restaurant ordering is a different intent and a different cart model.
8. **WhatsApp Flows / fancy multi-screen forms.** Buttons + lists are enough.
9. **Voice cloning** (Smallest.ai, Sarvam voice clone) so Saathi sounds like Deep or a known voice. Tempting; not week-1.
10. **Real-time TTS streaming** via WebSocket. Sarvam supports it in beta but you'd burn half a day on plumbing for a UX win mom won't notice.
11. **Per-user spend limits / fraud limits.** Hard-code a ₹2,500/order ceiling for now and ping Deep over Telegram for anything above. The "right" implementation is a v2 policy engine.
12. **Telegram / SMS fallback channel.** WhatsApp-only for v1.
13. **Web dashboard for Deep** to see all orders. Use CloudWatch logs + a daily DynamoDB scan emailed to yourself. Build the dashboard once mom is actually placing 5+ orders/week.
14. **Multi-language** beyond Hindi/Hinglish. No Bengali, Marathi, etc. until somebody asks for it.
15. **Self-hosted ASR/TTS** (AI4Bharat, IndicConformer). Beautiful, free, way too much yak-shaving for week 1.
16. **Computer Use / agentic vision-based browser control** for sites that change selectors weekly. Day 6's polish pass adds Stagehand as a fallback, but full Anthropic Computer Use is v2.

## 11. Day-1 checklist — do these in the next 24 hours

If you do nothing else today, do these. In this order. They unblock the entire week and the items with the longest external wait should fire first.

### The high-leverage Day-1 sequence (4–6 hours of focused work)

**☐ 1. Buy the second SIM right now.** Walk to the Jio store. ₹239 prepaid, eSIM if your dev phone supports it. This SIM is Saathi's phone. Without it, you can't register WhatsApp Cloud API without nuking mom's existing WhatsApp. (30 min)

**☐ 2. File the long-lead-time access requests in parallel — these are the bottlenecks for the *whole* week:**
   - Open a `mcp client request` issue on `github.com/Swiggy/swiggy-mcp-server-manifest` with your use case (one paragraph) and your callback URL (`https://saathi.yourdomain.in/oauth/swiggy/callback`). (10 min)
   - Email Tata 1mg's merchant team via the contact form at `onedoc.1mg.com` requesting merchant API access for a "personal health assistant" pilot. Include your Aadhaar/PAN to speed up KYC. (15 min)
   - Sign up at `razorpay.com/agentic-payments` for the waitlist. Won't help week 1, but you want to be in the queue. (5 min)

**☐ 3. Provision the boring infra:**
   - Create a Meta Developer account; create the WhatsApp app; add mom's number as test recipient; generate a permanent access token. (45 min)
   - Spin up Lightsail Mumbai (2 GB, ₹830/mo); attach static IP; install Python 3.12 + Caddy; point `saathi.yourdomain.in` at it. (45 min)
   - Anthropic Console signup + $20 credit; AWS Bedrock model access request for Sonnet 4.6 and Haiku 4.5 in `ap-south-1`. (15 min)
   - Sarvam AI signup; claim ₹1,000 free credit; test Saaras v3 + Bulbul v3 in their playground with a recording of mom's voice. (20 min)
   - Browserbase free-tier signup; create a project; save the API key. (10 min)
   - DynamoDB table `saathi` in `ap-south-1`, `pk` + `sk` string keys, on-demand billing, TTL attribute `ttl`. (5 min)

**☐ 4. Submit the WhatsApp utility template for review** (it will sit in queue 24–48 h, so submit on Day 1 even though you'll only use it on Day 4–5):

```
Name: saathi_order_status
Category: UTILITY
Language: Hindi (hi)
Body: नमस्ते {{1}}, आपका {{2}} ऑर्डर {{3}} है। समय: {{4}}।
        अगर कुछ बदलना है, एक voice note भेजिए।
Example values: {{1}}=Mom, {{2}}=दवा, {{3}}=रवाना हो गया, {{4}}=15 मिनट
```

   Submit a second variant with slightly different phrasing as a hedge against rejection.

**☐ 5. Deploy the ack-and-echo webhook** (the bare-bones FastAPI app from §5.4 above) and confirm a text "hello" → text "नमस्ते मम्मी" round-trip works end-to-end on mom's WhatsApp. **If this works by EOD Day 1, the entire week is on track.**

**☐ 6. Set up your own Telegram bot for concierge alerts** (BotFather, 5 min). This is the human-in-the-loop channel for Days 5–7's bill pay flow. Don't skip — Day 5 you'll need it.

**☐ 7. Pre-curate mom's data in DynamoDB:**
   - Her exact delivery address + pin code.
   - Her usual 8–10 grocery items (read off her last Blinkit/BigBasket history).
   - Her 5–8 regular medicines with brand, dose, frequency.
   - JVVNL electricity consumer number (off her last bill).
   - Mobile recharge plan / operator / circle.
   - One recent prescription image, uploaded to S3.

   Without this seed data, Saathi can't be useful on Day 3. Build it now.

**☐ 8. Take mom out for chai** and tell her what you're building. Get her recorded voice consent ("हाँ, Deep मेरे लिए दवा और सामान order कर सकता है, Saathi भी"). This is your legal cover and also a baseline voice sample you'll need anyway for testing pronunciation.

---

### Concrete repos & libraries to clone today

- **Anthropic Claude quickstarts**: `github.com/anthropics/claude-quickstarts` — has working `computer-use-demo`, `customer-support-agent`, and tool-using agent samples. Clone, run the customer support one as a template.
- **Sarvam Python SDK**: `pip install sarvamai==4.23.2`. Docs at `docs.sarvam.ai`.
- **Claude Agent SDK**: `pip install claude-agent-sdk`. Docs at `code.claude.com/docs/en/agent-sdk/overview`. Has built-in MCP support out of the box.
- **whatsapp-cloud-api-python** (community SDK) or just `httpx` — the Cloud API is simple enough that a 50-line wrapper covers everything you need; don't take on dependency weight.
- **Playwright Python**: `pip install playwright && playwright install chromium`.
- **Stagehand** (Browserbase's AI-augmented Playwright): `pip install stagehand-py` (or `npm install @browserbasehq/stagehand`). Worth it for resilient selectors on Blinkit/PharmEasy.
- **Swiggy MCP**: no SDK to clone — it's an HTTP MCP endpoint. Use any MCP client (the official Anthropic MCP Python SDK is in `claude-agent-sdk`).
- **Tata 1mg sample**: their docs at `onedoc.1mg.com/public_docs/content/Merchant Integration Documentation/Phamacy API Integration/api-integration/` have working cURL examples; no SDK, just REST + JWT.

---

### What "done" looks like on Day 7

A simple acceptance test, written in plain Hindi:

1. मम्मी कहती हैं *"Saathi, दूध-ब्रेड order कर दो"*. ✅ Order goes to Blinkit/Instamart on COD; ETA voice-reply lands within 20 seconds.
2. मम्मी कहती हैं *"मेरी BP की दवा खत्म हो गयी, मंगवा दो"*. ✅ Saathi reads back the drug name, confirms, orders on 1mg/PharmEasy COD, sends voice confirmation with order ID.
3. मम्मी कहती हैं *"बिजली का बिल भर दो"*. ✅ Saathi reads the amount + due date, gets her confirmation, pings Deep on Telegram; Deep pays in 30 s; Saathi voice-confirms to mom with the receipt image.
4. मम्मी कहती हैं *"रोको"* mid-flow. ✅ Saathi cancels the next action and confirms cancellation.
5. Same flow works tomorrow morning (cookies haven't expired, session state is durable). ✅

If 4 of those 5 work on Day 7, Saathi v1 is shipped, and you have an honest list of v2 priorities. Ship it; iterate live.

Good luck, Deep. Mom is going to love this.

---

## Closing notes — things this document deliberately *doesn't* answer

- **"Should mom use this instead of the Blinkit / 1mg apps?"** — Probably not yet. The honest pitch to her is: "If you don't feel like opening the app, send me a voice note." Saathi competes with friction, not with the apps themselves.
- **"What if Sonnet 4.7 drops mid-week?"** Anthropic pricing has held flat across 4.6 → 4.7 for both Sonnet and Opus. Switching is a one-line model-name change in the Agent SDK. Don't pre-optimise.
- **"Will mom understand Bulbul's voice?"** Test on Day 2. If she struggles with `vidya`, switch to `anushka` or `meera`. The voice is the single biggest UX lever.
- **"What about ChatGPT on WhatsApp?"** Banned for general-purpose use as of Jan 15, 2026, but Saathi is task-specific and is allowed. Don't conflate the two in your marketing copy if Saathi ever leaves the family.

### Source-quality caveats

A few of the inline figures above (especially BSP per-message rates, Browserbase $/hr, and Claude pricing) come from second-party blog roundups dated April–May 2026. The first-party rate cards on `business.whatsapp.com/products/platform-pricing`, `platform.claude.com/docs/en/about-claude/pricing`, `browserbase.com/pricing`, and `sarvam.ai/api-pricing` are authoritative — verify before committing budget. Meta has historically adjusted India template rates mid-year (the Jan 1, 2026 ~10% hike on marketing rates being the most recent).

A few timing-sensitive points where the public web is ahead of canonical docs:
- **Claude Opus 4.7** launched April 16, 2026 per the Anthropic docs and BenchLM.ai pricing analysis; documentation across the ecosystem is still mid-migration from 4.6 to 4.7 naming. Use either; output is similar.
- **Swiggy Builders Club** launched April 23, 2026 — the access program is fresh and the whitelist queue is still moving. Expect process changes through 2026.
- **Razorpay agentic UPI on Claude** is a *pilot* per Razorpay's own Feb 20, 2026 announcement — public availability claims should be treated as forward-looking until you have a working sandbox.

Build accordingly, and ship Saathi anyway. The hardest part isn't the technology — it's getting mom to remember she has a new friend on WhatsApp.