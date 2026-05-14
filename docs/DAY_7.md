# Day 7 — Mom uses it for real

**Goal by EOD:** Mom uses Saathi unassisted for one full day, places at least 2 real orders, and the bot survives. Deep observes silently and fixes the top 3 issues.

**Out of scope today:** Building anything new. Today is observation + targeted fixes.

## The frame for Day 7

Day 7 is the only day where the work is mostly *not* coding. It's watching, listening, and making small surgical fixes. Resist the urge to refactor anything. Resist the urge to add a feature Mom suggests ("oh, can you also pay my LIC premium?"). Write it down for v2. Ship Saathi v1.

## Morning: the formal handoff (60 min, with Mom)

Sit with her at the kitchen table. Phone in hand. Bring chai.

### The 5-minute briefing

Tell her, in her own language:
1. **What Saathi can do**: order medicine, groceries, pay the electricity bill and Jio recharge.
2. **What she does**: send a voice note like she'd send to you. Whatever feels natural.
3. **What she doesn't do**: type, navigate menus, tap multiple buttons. Just talk.
4. **How to cancel**: say "रोको" or "रद्द करो" any time. Saathi will stop.
5. **When something is wrong**: Saathi will tell her. Or she can voice-note "Deep को बताओ" and you'll get a message.

Don't overload her with rules. The 4 bullets above are enough.

### Three guided test orders

Have her place these three, while you watch silently. Don't help unless she's truly stuck.

1. **Test 1 — easy**: *"दूध और ब्रेड मंगवा दो"*. Grocery, no ambiguity.
2. **Test 2 — slightly harder**: *"Telma 40 खत्म हो गयी"*. Medicine, name + dose.
3. **Test 3 — bill**: *"बिजली का बिल भर दो"*. Concierge mode — she sees Saathi confirm, you get a Telegram ping, you pay, she gets a receipt.

After each, ask: "क्या लगा? आसान था?" Note her unfiltered reaction.

### Pre-emptive coaching (only after the three tests)

If she struggled with any pattern, gently coach:
- If she shouted at the phone because the reply took 8 seconds: explain the interim ack is acknowledgment ("देख रही हूँ" means "I'm working on it, just wait").
- If she repeated the same voice 3 times: tell her once is enough.
- If she said yes by voice instead of tapping the button: it works, but tapping is faster.

## Afternoon: silent observation (4 hours, async)

Leave her alone. Go to your own work. Don't hover.

Set up:
- CloudWatch Logs dashboard pinned to a browser tab. Filter for `level=ERROR` and `level=WARNING`.
- Telegram bot foregrounded on your phone. Concierge alerts come through.
- The S3 bucket open in another tab so you can listen back to her voice notes if something goes wrong.

Things to log proactively (do not address in real time unless Saathi is broken):

| What | Where you see it | What to do |
|---|---|---|
| Failed STT (low confidence transcript) | CloudWatch | Add to fix list |
| Sonnet tool-call loop (hit max_turns) | CloudWatch | Add to fix list |
| Executor exception | CloudWatch | Triage: is Saathi recovering gracefully? |
| Mom says the same thing twice in 30s | DDB session log | Interim ack might be too slow. Fix list. |
| Mom uses the bot and then immediately calls you on the phone | Phone call! | Definitely a bug. Take note. |
| Mom asks for something Saathi doesn't do | Voice note | v2 backlog |
| Mom places a successful order | Order in DDB | Quietly celebrate |

## Evening: the fix sprint (2–3 hours, alone)

Look at the day's logs. Find the top 3 issues by impact. Fix them. Deploy.

Likely top issues (predicting):

1. **STT confused by an accent quirk on a specific word.** Add to `PRONUNCIATION_OVERRIDES` if it's a known brand; if it's a generic word, the only fix is to widen the intent classifier's tolerance.
2. **A button tap arrived after the bot timed out the session.** Extend session TTL from 24h to 48h, or remove the agent-loop timeout entirely.
3. **The interim ack was 4 seconds, not 2.** Optimize: pre-cache the media_id (don't re-look-up DDB), use HTTP/2 to Meta, skip the SQS step if you added one.

Don't fix issues that occurred once. Fix what happened 3+ times.

## Documenting v1

Before shipping the final version, write/update these:

### `docs/STATUS.md` — final v1 state
What works. What's stubbed. What's deferred. What broke and got fixed.

### `docs/RUNBOOK.md` — operational guide for future-Deep
- How to check if Saathi is up: `curl https://saathi.<domain>/healthz`
- How to read the logs
- How to re-OTP a session when cookies expire (you will need this in ~30 days)
- How to roll back if a deploy breaks things
- The list of secrets in Secrets Manager and how to rotate them
- WhatsApp template names and how to submit new ones

### `docs/V2_BACKLOG.md` — everything Mom asked for that isn't in v1
- "Can you also pay LIC?" → v1.1 (add LIC to billers config)
- "Can it order from BigBasket too?" → v2
- "Can it remind me to take medicine?" → v3 (proactive flows, not in scope for now)

### `docs/COSTS.md` — actual spend for week 1
Compare against the PLAN estimate. Did Sarvam credits run out? Did Browserbase need an upgrade? Did Bedrock cost more than expected?

## Acceptance criteria (the real ones)

These are the criteria from PLAN §6, and they're the only acceptance criteria that matter:

- [ ] Mom says *"Saathi, दूध-ब्रेड order कर दो"*. Order on COD, ETA voice-reply within 20 seconds.
- [ ] Mom says *"मेरी BP की दवा खत्म हो गयी, मंगवा दो"*. Saathi reads back drug name, confirms, orders on 1mg/PharmEasy COD, voice confirmation with order ID.
- [ ] Mom says *"बिजली का बिल भर दो"*. Saathi reads amount + due date, gets her confirm, pings Deep on Telegram, Deep pays in 30 s, Saathi voice-confirms to Mom with receipt image.
- [ ] Mom says *"रोको"* mid-flow. Saathi cancels the next action.
- [ ] Same flows work tomorrow morning (cookies haven't expired overnight).

**4 of 5 working = v1 is shipped.** Don't gate on perfection.

## What success looks like

A week from now, Mom voice-notes Saathi *without telling Deep first*. That's the metric. Not P50 latency, not order accuracy, not test coverage. The metric is: does she reach for Saathi when no one is watching?

If yes, you built something real. Iterate from there.

If no, sit with her and find out why. The honest answer might be that she prefers the apps (some older users genuinely enjoy grocery shopping as agency). That's data; respect it. The fallback is to position Saathi as the *low-effort* option, not the *replacement*.

## What NOT to do today

- Do not start v2. Even if the day is going great. Especially if it's going great.
- Do not add features Mom requested in real time. Write them down.
- Do not refactor. Today is for fixes, not improvements.
- Do not announce Saathi to anyone outside the family. v1 is for Mom. Period.
- Do not skip the runbook. Future-Deep will thank present-Deep.

## EOD ritual — the closing

Update `docs/STATUS.md` with the final v1 state. Tag the git repo: `git tag -a v1.0.0 -m "Saathi v1.0.0 — Mom-tested"`.

Then close the laptop and call Mom to ask how her day was.

That's the real win.

---

## Post-mortem prompts for the weekend after Day 7

These are for Saturday/Sunday, after you've slept. Don't try to answer them on Day 7.

1. **What was the hardest 30 minutes of the week?** That's a v1.1 architectural fix candidate.
2. **Which executor failed most often?** That's a v1.1 reliability target.
3. **Did Mom use voice notes or did she end up texting?** If she texted, the voice loop has UX friction we missed.
4. **Did Mom ask Saathi for anything Saathi can do but didn't recognize?** That's a system prompt bug.
5. **Would Mom recommend Saathi to her sister?** If yes, you have a v2 opportunity (start with the family-shared-accounts deferred feature). If no, why not — and is it fixable?

Answers go into a new `docs/POSTMORTEM_v1.md` after the weekend. That doc becomes the input to v2 planning.

Ship v1. Sleep. Then plan v2.
