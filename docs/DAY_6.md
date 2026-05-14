# Day 6 — Polish: the मम्मी UX pass

**Goal by EOD:** Saathi feels like a real, considerate assistant — not a working tech demo. All three flows have interim acks, graceful failures, digit-by-digit amount confirmations, the abort command, and Hindi failure messages.

**Out of scope today:** New flows. New executors. Architecture changes.

## The frame for Day 6

Days 1–5 built capability. Day 6 makes it kind. Every change today is about how Mom experiences a slightly-slow or slightly-confused bot. The bot does not have to be perfect; it has to be *graceful when it's not perfect.*

If you find yourself building a new tool today, you're off-task.

## The 7 polish items, in priority order

### Polish 1 — Always-on interim acknowledgment ⭐ highest impact

The single biggest UX win. Every voice note gets a 1-second voice ack within 2 seconds. **Without this, Mom will re-send 3 times whenever the bot takes more than 5 seconds.**

Implementation:
- In `app.py`'s audio handler, **before** STT/LLM, fire-and-forget a TTS of a short pre-cached ack: *"ठीक है मम्मी, देख रही हूँ"*.
- Pre-render this MP3 once, store in S3 (`saathi-media/system/ack_dekh_rahi_hoon.mp3`), keep the Meta media_id cached in DDB. Send it directly via `whatsapp.send_audio()` — no Sarvam call needed per interaction.
- Three variants, randomly picked:
  - *"ठीक है मम्मी, देख रही हूँ"*
  - *"एक minute मम्मी, check करती हूँ"*
  - *"हाँ मम्मी, सुन लिया, थोड़ा रुकिए"*
- Use a different ack for executor-bound turns (`"order लगा रही हूँ, थोड़ा time लगेगा"`) vs simple queries.

Mom should never feel ignored.

### Polish 2 — Digit-by-digit amounts for ≥ ₹1000

Mom is conservative with money. For amounts ≥ ₹1000, after the natural Hindi phrasing, the voice repeats the amount digit by digit:

*"तीन हज़ार दो सौ चालीस रुपये — तीन… दो… चार… शून्य रुपये।"*

Implementation in `utils/hindi.py`:
```python
def rupees_for_confirmation(amount: int) -> str:
    """For amounts ≥ ₹1000, returns 'X रुपये — digit by digit'.
    Below ₹1000, just the natural phrasing.
    """
```

Inject this into every `speak_to_mom` call where an amount appears. Sonnet prompt update: "When confirming any spend ≥ ₹100, call format_amount_for_voice with the rupee amount and include it verbatim in your text."

### Polish 3 — The "रोको" command

Mom should be able to cancel any in-flight agent action with a voice "रोको" / "रद्द करो" / "cancel" / "रुक जा".

Implementation:
- New server-side flag: DDB `pk=mom, sk=session#<conv_id>` gets an `abort: true` field on every new voice note from Mom while a session is active.
- Every tool invocation in `orchestrator.py` checks the abort flag before executing. If set, raise `AbortedByUser` and reply with *"ठीक है मम्मी, रोक दिया।"*
- The abort flag is detected by classifying the *first 3 seconds* of the new voice note. If it contains a stop keyword, mark abort=true *before* the regular intent classification runs.

Detection: a tiny separate Haiku call on the new transcript with a stop-keyword classifier. Fast and cheap.

Test: start an order, mid-flow send a "रुक जा" voice → assert order is NOT placed and Mom gets the abort ack.

### Polish 4 — Hindi failure messages

Pre-write 8 failure responses, all in Hindi. Currently the bot probably says "Sorry, I encountered an error" or worse, English stack traces. That's broken UX for Mom.

In `messaging/templates.py`:
```python
FAILURE_VOICES = {
    "executor_timeout": "मम्मी, अभी थोड़ी technical दिक्कत है, 5 minute में try करूंगी।",
    "out_of_stock": "मम्मी, {item} अभी available नहीं है, कुछ और मंगवा दूं?",
    "session_expired": "मम्मी, login refresh करना है, Deep को बता दिया है।",
    "unclear_intent": "मम्मी, समझ नहीं आया ठीक से, एक बार और बोलिए?",
    "pin_not_serviceable": "मम्मी, आपके area में {service} delivery नहीं है अभी।",
    "amount_too_high": "मम्मी, ये बहुत बड़ा amount है, Deep से confirm करना पड़ेगा।",
    "network_error": "मम्मी, internet में दिक्कत है, थोड़ी देर बाद try करूं?",
    "generic": "मम्मी, कुछ problem है, Deep को बता दिया, थोड़ी देर में ठीक हो जाएगा।"
}
```

Pre-render each as MP3, cache the Meta media_ids in DDB. Failure responses go out in <1s — no Sarvam call.

### Polish 5 — Stagehand fallback for selector breakage

When Playwright selectors break (Blinkit redesigns a button, 1mg changes class names), the executor currently throws and Saathi fails the order. Stagehand can recover with AI-powered selector resolution.

Implementation:
- Wrap critical Playwright actions (`add_to_cart`, `checkout_cod`) in try/except.
- On `PlaywrightTimeoutError` or `ElementNotFound`, retry **once** with Stagehand's natural-language action: `await page.act("click the 'Add to cart' button for the product matching 'Telma 40'")`.
- If Stagehand also fails, escalate to Deep.

Don't replace Playwright with Stagehand wholesale. Stagehand is slower and costlier. Use it as the recovery layer.

### Polish 6 — Confidence-gated escalation

Sonnet sometimes barrels ahead with low confidence. Add explicit confidence checks:

- Before calling `place_*_order`, the LLM must indicate confidence in its understanding. Implement via a `confirm_understanding(summary: str, confidence: float)` tool the LLM must call before any irreversible action.
- If confidence < 0.85, force a second confirmation: bot reads back the order in voice + button, regardless of how unambiguous Mom's request seemed.
- This catches the cases where Sonnet hallucinates SKU substitutions.

### Polish 7 — Latency profiling and pre-warming

By Day 6, you have real timing data. Find the top 2 latency offenders:

Likely culprits (in rough order):
1. **Browserbase cold start** (5–15s per session). Solution: pre-warm a Browserbase session at the start of every agent turn that classifies as `medicine` or `grocery`. Throw it away if not used after 2 min.
2. **First Sarvam call of the day** (warmup latency). Solution: ping Sarvam every 4 minutes with a 1-byte test request as a cron.
3. **Bedrock model cold start** in `ap-south-1`. Solution: provisioned throughput is overkill; just be aware that the first call of the day is ~200ms slower.

Don't optimize speculatively. Look at the CloudWatch latency logs from Days 3–5 and pick the two worst offenders.

## Bonus polish (only if time)

- **Voice tone adjustment.** Day 2 picked `vidya` or `anushka`. Re-evaluate now that Mom has heard the bot in real flows. She may want slower (`pace=0.9`) or warmer (different voice).
- **Time-of-day greeting variation.** Morning: *"नमस्ते मम्मी"*. Evening: *"शुभ संध्या मम्मी"*. Past 10pm: *"मम्मी, इतनी रात को सब ठीक है?"* (caring nudge).
- **Order receipt formatting.** When Mom gets the order ID after a successful purchase, send it as a text message with structured info (date, items, amount, ETA) alongside the voice. She can scroll back later.

These are nice-to-haves. Skip if Polish 1–7 are eating the day.

## Files touched

Realistically, Day 6 touches:
- `src/saathi/app.py` — interim ack wiring
- `src/saathi/utils/hindi.py` — digit-by-digit formatting
- `src/saathi/llm/orchestrator.py` — abort flag check, confidence gate
- `src/saathi/llm/prompts.py` — confidence-gate instructions
- `src/saathi/messaging/templates.py` — failure voices
- `src/saathi/executors/medicine_1mg.py` — Stagehand fallback
- `src/saathi/executors/grocery_blinkit.py` — Stagehand fallback
- `scripts/prerender_system_voices.py` — one-shot script to generate and upload the static voice files

Don't restructure. Don't refactor.

## Tests

### Updated tests
- Abort flag: simulated voice with "रोको" mid-flow → assert no order placed, abort message sent.
- Digit-by-digit: `rupees_for_confirmation(3240)` returns the right format.
- Failure voices: each failure path triggers the correct pre-rendered voice.

### New end-to-end test
`scripts/smoke_test.py --full` runs all three flows in sequence against the dev environment, asserting:
1. Interim ack arrives within 2.5s of voice note.
2. Each flow's final confirmation arrives within the SLA (medicine: 60s, grocery: 90s, bill: 45s to summary).
3. P50 latency logged and printed.

## Acceptance criteria

- [ ] Every voice note gets an interim ack within 2.5 seconds.
- [ ] Amounts ≥ ₹1000 are spoken twice: natural Hindi, then digit by digit.
- [ ] "रोको" mid-flow aborts cleanly within 5 seconds.
- [ ] All 8 failure scenarios produce Hindi voice replies, no English fallbacks anywhere.
- [ ] Stagehand fallback successfully recovers from at least one Playwright timeout (induce one by changing a CSS selector and watching the bot recover).
- [ ] No order ≥ ₹1000 placed without an explicit confidence gate + button confirm.
- [ ] P50 latency for each flow is logged and meets target.
- [ ] All existing tests still green.

## Reality checks

1. **Sit with Mom and try to break the bot intentionally.** Talk over it. Send a voice note while it's still replying. Say something ambiguous. Watch how it behaves.
2. **Measure interim-ack latency on Mom's actual phone.** A 2-second target on the server may translate to 4 seconds on her phone due to WhatsApp delivery delays. Tune accordingly.
3. **Listen to the failure voices.** Bulbul's pronunciation of "technical दिक्कत" is fine; her pronunciation of "session" or "internet" may be off. Adjust the wording until it sounds natural.

## Stop conditions

- Interim acks introduce double-replies (Mom hears the ack and then the real reply, and gets confused). Mitigation: only send ack if estimated work > 4 seconds.
- Abort flag misfires (Mom says "और तो रोको कर देती हूँ" — "okay let me stop" — bot aborts when she didn't mean to). Tighten the keyword classifier to require an imperative form near the start of the utterance.
- Stagehand inflates latency to >15s per recovered action. Cap retries at 1 and prefer a graceful failure voice over a slow recovery.

## What NOT to do today

- Do not add a fourth flow. Three is the v1 promise.
- Do not optimize Sarvam costs. ₹17/week is fine.
- Do not introduce caching beyond the pre-rendered voices and bill cache. Premature.
- Do not refactor module boundaries. The shape is fine.
- Do not add observability tooling beyond CloudWatch + structured logs. No Datadog, no Sentry, no PostHog.

## EOD ritual

Update `docs/STATUS.md`. List which polishes shipped, which got descoped to v1.1. Note any new bugs found during the "break it intentionally" session.

Tomorrow is Day 7: Mom uses it for real, alone, on her own phone. Today's polish is what makes that feel like an assistant, not a demo.
