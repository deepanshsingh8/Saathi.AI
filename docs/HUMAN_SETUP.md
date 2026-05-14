# Saathi — Human Setup Runbook

Everything you (Deep) need to do **personally**, in one document. The code is being written ahead in parallel; this is what unblocks the end-to-end test on Mom's WhatsApp.

**Total time, focused:** 6–8 hours of your time, spread across 3–14 days because some steps have queue waits (Swiggy MCP whitelist, 1mg merchant API, WhatsApp template review, Mom's OTP availability).

**Order matters.** File the long-leads on Day 1 of *your* setup. They block downstream work for days.

---

## At a glance — what this gets you

By the end of this doc, the following are true:

- Saathi has its own phone number on WhatsApp Cloud API
- Mom's number is on the test-recipients list and can send/receive
- A Lightsail box in Mumbai serves `https://saathi.<your-domain>/healthz` over HTTPS
- All API keys (Sarvam, Anthropic, Browserbase, Telegram) are in `.env` on the box
- DynamoDB table `saathi` exists in `ap-south-1` with Mom's profile seeded
- S3 bucket `saathi-media` exists with KMS encryption
- Playwright `storage_state` JSON files for 1mg and Blinkit are in Secrets Manager
- The Telegram concierge bot is reachable from the FastAPI process

---

## 0 · Cost expectation (before you commit)

| Line item | One-time | Monthly |
|---|---|---|
| Saathi prepaid SIM | ₹239 | ₹0 (incoming free; keep with low recharge) |
| Lightsail Mumbai 2 GB | — | ₹830 (~$10) |
| Anthropic credit (back-up to Bedrock) | ₹1,700 ($20) | usage-based, ~₹1,000/mo expected |
| Sarvam credit | ₹0 (₹1,000 free on signup) | ~₹450 expected |
| Browserbase Developer plan | — | ₹1,660 ($20) (free tier first; upgrade Day 3–4) |
| AWS (DDB + S3 + Bedrock + Secrets Manager) | — | ~₹150 |
| WhatsApp Cloud API | ₹0 | ₹0 (all in 24h service window) |
| **Total Month 1** | **~₹2,000** | **~₹4,000** |

Comfortable hobby budget. If any line surprises you in Week 2, log it in `docs/COSTS.md`.

---

## 1 · Long-lead requests — file these FIRST (15 min, then walk away)

These have multi-day SLAs. File them all on Day 1 of your setup so they bake while you do everything else.

### 1.1 Swiggy MCP whitelist
- **Where:** https://github.com/Swiggy/swiggy-mcp-server-manifest
- **Action:** Open a new issue with the label `mcp client request`.
- **Body to paste:**
  > **Use case:** Personal commerce assistant for family (Hindi/Hinglish-speaking parent in Jaipur). Voice-note → COD order on Instamart.
  > **Volume:** ~10 orders/week, single user.
  > **Callback URL:** `https://saathi.<your-domain>/oauth/swiggy/callback`
  > **Contact:** <your email>
- **SLA:** 3–14 days. May not arrive in time. Code defaults to **Path B (Blinkit Playwright)**.

### 1.2 Tata 1mg merchant API
- **Where:** https://onedoc.1mg.com (contact form), or `merchant-support@1mg.com`
- **Action:** Email with subject `Merchant API access — personal health assistant pilot`. Attach PAN.
- **Body to paste:**
  > Hi 1mg merchant team,
  > I'm building a personal health assistant for my mother (~60, Jaipur, PIN 302017) that helps her reorder her regular medicines via voice notes on WhatsApp. COD only. Volume <20 orders/month. I'd like merchant API access so the bot can use the official `Create Order API` rather than browser automation.
  > PAN attached. Happy to provide any other docs.
  > Thanks, Deep
- **SLA:** 3–14 days. Code defaults to **Playwright on 1mg/PharmEasy** if not approved.

### 1.3 Razorpay agentic UPI waitlist
- **Where:** https://razorpay.com/agentic-payments
- **Action:** Sign up, add a one-line use case.
- **SLA:** Won't help v1 (COD-only). You just want to be in the queue for v2.

---

## 2 · Get Saathi a phone (Block A — 60 min, physical)

1. Walk to a Jio or Airtel store.
2. Buy a **prepaid SIM in your name** (₹239).
3. Activate it in a spare handset, **or** as eSIM on your secondary line.
4. **DO NOT install consumer WhatsApp on this number.** Cloud API will refuse to register a number that already has WhatsApp. If you slip up, you'll wait 24h before re-trying.

The number you just bought = **Saathi's number**. Mom messages this.

---

## 3 · Meta WhatsApp Cloud API (Block C — 45 min)

### 3.1 Developer signup
1. Go to https://developers.facebook.com → "My Apps" → "Create App".
2. App type: **Business**. Use case: **Other**. Continue.
3. App name: `Saathi`. Contact email: yours. Create.
4. Add the **WhatsApp** product. (You'll see it in the left rail.)

### 3.2 Register Saathi's phone number
5. Open **WhatsApp → API Setup**. Note the **WABA ID** and the temporary **Phone Number ID** (you'll replace this when you add your real number).
6. Click **Add phone number** → enter Saathi's SIM number → request OTP. Enter OTP from the SIM.
7. After verification, the new number becomes the Phone Number ID for the `WA_PHONE_ID` env var.

### 3.3 Add Mom as a test recipient
8. Same panel → **Test recipient** → click **Add phone number** under "To" → enter Mom's number → she'll get a verification code on WhatsApp; type it back in.
9. (Optional) Add your own number too for dev testing.

### 3.4 Generate the System User token
10. Go to **Business Settings** (Meta Business Suite) → **Users → System Users** → **Add**.
11. Name: `saathi-prod`. Role: Admin. Create.
12. On the new system user, click **Generate New Token**.
13. App: pick the Saathi app. Token expiration: **Never**. Permissions: tick `whatsapp_business_messaging` and `whatsapp_business_management`.
14. **Copy the token NOW.** You can't see it again. Paste into `.env` as `WA_ACCESS_TOKEN`.

### 3.5 Pull the App Secret
15. **App settings → Basic** in the dev console → **App Secret → Show**. Paste into `.env` as `WA_APP_SECRET`.

### 3.6 Pick a webhook verify token
16. Make up any random string (e.g. `openssl rand -hex 16`). Paste into `.env` as `WA_VERIFY_TOKEN`. You'll set the same string in the Meta dashboard during webhook configuration (step 9 below).

### 3.7 Submit the utility templates (DO THIS NOW — 24–48h review)
17. **WhatsApp → Message Templates → Create template**:
    - Name: `saathi_order_status`
    - Category: `UTILITY`
    - Language: `Hindi (hi)`
    - Body:
      ```
      नमस्ते {{1}}, आपका {{2}} ऑर्डर {{3}} है। समय: {{4}}।
      अगर कुछ बदलना है, एक voice note भेजिए।
      ```
    - Sample values: `{{1}}=Mom`, `{{2}}=दवा`, `{{3}}=रवाना हो गया`, `{{4}}=15 मिनट`
18. Submit.
19. **Submit a hedge variant** with slightly different phrasing — name it `saathi_order_status_v2`. If one gets rejected for arbitrary reasons, the other usually survives.

You'll come back to **webhook configuration** in §9 after the Lightsail box is up.

---

## 4 · Other accounts (Block D — 45 min, all online)

### 4.1 Anthropic Console (backup path)
1. https://console.anthropic.com → sign up → **Billing → Add credit → $20**.
2. **API Keys → Create key**. Name: `saathi-prod`. Copy → `.env` as `ANTHROPIC_API_KEY`.

### 4.2 AWS Bedrock model access
3. AWS console → switch region to **Mumbai (`ap-south-1`)**.
4. **Bedrock → Model access → Manage**.
5. Tick **Anthropic Claude Sonnet 4.6** and **Anthropic Claude Haiku 4.5**.
6. Submit. For accounts with billing history, approval is **instant**. New accounts: ~24h.
7. Verify approval shows green next to both model names.

### 4.3 Sarvam AI
8. https://sarvam.ai → sign up.
9. Console → **Billing** → **Claim ₹1,000 free credit**.
10. **API Keys → Create**. Copy → `.env` as `SARVAM_API_KEY`.
11. **Sanity check:** Sarvam playground → upload any 5-second Hindi voice clip → confirm Saaras v3 returns a clean transcript. If it returns garbage on your accent, file a Sarvam support ticket — your build will not work.

### 4.4 Browserbase
12. https://browserbase.com → sign up (free tier first).
13. **Project → Settings → API Keys → Copy**. Paste → `.env` as `BROWSERBASE_API_KEY`.
14. Copy the Project ID → `.env` as `BROWSERBASE_PROJECT_ID`.
15. (Day 3–4) Upgrade to **Developer plan ($20/mo)** when free tier's 1 browser-hour exhausts. You'll likely hit this on first 1mg login attempt.

### 4.5 Telegram concierge bot (5 min)
16. Open Telegram → search **@BotFather** → start chat.
17. Send `/newbot`. Name: `Saathi Concierge`. Username: anything ending in `_bot` (e.g. `saathi_concierge_bot`).
18. BotFather replies with a **token**. Copy → `.env` as `TELEGRAM_BOT_TOKEN`.
19. **Get your chat_id:**
    1. DM your new bot once (any message).
    2. Open in browser: `https://api.telegram.org/bot<TOKEN>/getUpdates`
    3. Find `"chat":{"id":<NUMBER>, ...}`. Copy that number → `.env` as `TELEGRAM_DEEP_CHAT_ID`.
20. Pick a webhook secret: `openssl rand -hex 16` → `.env` as `TELEGRAM_WEBHOOK_SECRET`. (You'll wire this up after the box is live, §11.)

---

## 5 · Lightsail Mumbai box (60 min)

### 5.1 Provision
1. AWS Lightsail console → **Create instance**.
2. Region: **Mumbai (ap-south-1)**.
3. Platform: **Linux/Unix** → Blueprint: **Ubuntu 22.04 LTS**.
4. Plan: **2 GB / 2 vCPU / 60 GB SSD** (~$10/mo).
5. Name: `saathi`. Create.
6. After it boots, **Networking → Attach static IP** (free while attached). Note the IP.

### 5.2 DNS
7. In your domain registrar (Cloudflare/Namecheap/etc.) add an **A record**: `saathi.<your-domain>` → `<static-IP>`. TTL low (300s) for now; raise later.
8. Wait 1–5 minutes. Verify: `dig +short saathi.<your-domain>` returns the IP.

### 5.3 SSH and base setup
9. Lightsail → **Connect using SSH** (or download the default key and ssh from your laptop).
10. On the box, run:
    ```bash
    sudo apt update && sudo apt -y upgrade
    sudo apt -y install python3.12 python3.12-venv python3-pip git debian-keyring debian-archive-keyring apt-transport-https curl
    curl -LsSf https://astral.sh/uv/install.sh | sh
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
    uv --version  # should print
    ```

### 5.4 Caddy (auto-HTTPS)
11. Install Caddy:
    ```bash
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
    sudo apt update && sudo apt -y install caddy
    ```
12. Drop in the project's Caddyfile (after you clone — see §5.5):
    ```bash
    sudo cp /home/ubuntu/saathi/scripts/Caddyfile /etc/caddy/Caddyfile
    sudo sed -i 's/saathi.example.in/saathi.<your-domain>/' /etc/caddy/Caddyfile
    sudo systemctl reload caddy
    ```
13. Verify Caddy log shows it issued a Let's Encrypt cert: `sudo journalctl -u caddy -n 50`.

### 5.5 Lightsail firewall
14. Lightsail → **Networking** tab → **IPv4 Firewall**: ensure **HTTPS (443)** and **HTTP (80)** are open. SSH (22) stays open. Block everything else.

### 5.6 Clone the repo
15. On the box:
    ```bash
    cd ~
    git clone <your-saathi-repo-url> saathi
    cd saathi
    uv sync --extra dev
    ```
16. Install Playwright Chromium (needed for executors):
    ```bash
    uv run playwright install --with-deps chromium
    ```

### 5.7 Configure `.env`
17. `cp .env.example .env`
18. Fill in all the values you collected in §3, §4. Don't commit `.env` (it's gitignored, but double-check: `git status` should not show it).

### 5.8 Systemd unit
19. Install:
    ```bash
    sudo cp /home/ubuntu/saathi/scripts/saathi.service /etc/systemd/system/saathi.service
    sudo systemctl daemon-reload
    sudo systemctl enable saathi
    sudo systemctl start saathi
    sudo systemctl status saathi  # should be active (running)
    ```
20. Sanity check: `curl -s http://127.0.0.1:8000/healthz` → `{"ok":true,"service":"saathi"}`.
21. Public sanity: from your laptop, `curl -s https://saathi.<your-domain>/healthz` → same JSON.

---

## 6 · AWS resources (15 min)

### 6.1 DynamoDB table
1. AWS console → DynamoDB (region **Mumbai**) → **Create table**.
2. Name: `saathi`. PK: `pk` (String). SK: `sk` (String).
3. Settings: **On-demand** capacity. **Encryption: AWS-owned key** (or KMS if you want).
4. **TTL:** after creation → table → **Additional settings → Time to live (TTL)** → enable on attribute name `ttl`.
5. Verify: `aws dynamodb describe-table --table-name saathi --region ap-south-1`.

### 6.2 S3 bucket
6. AWS console → S3 (region **Mumbai**) → **Create bucket**.
7. Name: `saathi-media-<your-suffix>` (must be globally unique).
8. **Block all public access**: yes.
9. **Default encryption:** AWS KMS (SSE-KMS), key: AWS-managed `aws/s3` is fine for v1.
10. Update `.env` on the box: `S3_BUCKET=saathi-media-<your-suffix>`. `sudo systemctl restart saathi`.

### 6.3 IAM permissions
11. AWS console → IAM → **Users → Add user** named `saathi-prod`.
12. **Access type: Programmatic**.
13. Attach inline policy `saathi-runtime`:
    ```json
    {
      "Version": "2012-10-17",
      "Statement": [
        {"Effect": "Allow", "Action": ["dynamodb:*"], "Resource": "arn:aws:dynamodb:ap-south-1:*:table/saathi*"},
        {"Effect": "Allow", "Action": ["s3:GetObject","s3:PutObject","s3:DeleteObject"], "Resource": "arn:aws:s3:::saathi-media-*/*"},
        {"Effect": "Allow", "Action": ["bedrock:InvokeModel","bedrock:InvokeModelWithResponseStream"], "Resource": "arn:aws:bedrock:ap-south-1::foundation-model/anthropic.*"},
        {"Effect": "Allow", "Action": ["secretsmanager:GetSecretValue"], "Resource": "arn:aws:secretsmanager:ap-south-1:*:secret:saathi/*"}
      ]
    }
    ```
14. Create access key. Add to `.env` as `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`. `sudo systemctl restart saathi`.

### 6.4 Secrets Manager
(You'll add the actual secrets in §8 after the manual logins.)
15. AWS console → Secrets Manager → confirm region is **Mumbai**. No setup yet — just confirm access.

---

## 7 · Mom's data (Block E — 30 min, in person)

This is the most important step. Do it with chai. Don't rush.

### 7.1 Recorded consent
1. On your phone, record her saying **clearly**:
   > हाँ, Deep मेरे लिए दवा, सामान और बिल का काम करवा सकता है, Saathi भी।
2. Save the file. You'll keep a copy at `~/saathi-private/consent.oga` on your laptop. Don't put it in git.

### 7.2 Profile data — write down on paper, then type into a JSON file
3. On your laptop, create `~/saathi-private/profile.json`:
   ```json
   {
     "name": "Mom",
     "phone": "+9198XXXXXXXX",
     "address": {
       "line1": "<flat / house no>",
       "line2": "<colony / locality>",
       "city": "Jaipur",
       "state": "Rajasthan",
       "pin": "302017"
     },
     "billers": {
       "electricity": {"provider": "JVVNL", "consumer_number": "<from latest bill>"},
       "mobile": {"operator": "Jio", "number": "+9198XXXXXXXX", "circle": "Rajasthan", "usual_amount": 299}
     },
     "medicines": [
       {"name": "Telma 40", "brand": "Telma", "dose": "40 mg", "frequency_days": 1, "search_hint": "Telma 40 mg tablet"},
       {"name": "Glycomet 500", "brand": "Glycomet", "dose": "500 mg", "frequency_days": 1, "search_hint": "Glycomet 500 mg"}
       /* … 5–8 of her regulars */
     ],
     "prescriptions": [
       {"s3_uri": "s3://saathi-media-<your-suffix>/mom/prescription/2026-05-rx.jpg", "doctor": "Dr X", "expiry": "2026-11-01"}
     ],
     "usual_basket": [
       {"name": "Amul Toned Milk 1L", "search_query": "Amul toned milk 1L", "quantity": 2},
       {"name": "Britannia Brown Bread", "search_query": "Britannia brown bread", "quantity": 1}
       /* … 8–10 staples */
     ]
   }
   ```
4. **Photograph one of her recent prescriptions clearly.** Crop and upload to S3:
   ```bash
   aws s3 cp ./prescription.jpg s3://saathi-media-<your-suffix>/mom/prescription/2026-05-rx.jpg --region ap-south-1
   ```
5. **Photograph her medicine strips** (so you can match them to 1mg search results visually).
6. Put `profile.json` somewhere your seed script can read it (e.g. `~/saathi-private/profile.json`).

### 7.3 Seed it into DynamoDB
7. From your laptop or the box, run:
   ```bash
   uv run python scripts/seed_profile.py --file ~/saathi-private/profile.json
   ```
   (This script lands as part of the Day 3 code drop; verify with the developer note in `tasks/todo.md`.)
8. Verify: AWS DDB console → table `saathi` → query `pk=mom, sk=profile` → see the profile.

---

## 8 · Manual OTP logins for the executors (45 min)

The Playwright executors authenticate as Mom on 1mg, PharmEasy, Blinkit. The first OTP login has to be human-driven (her phone gets the OTP, she reads it). Once stored, the cookie lasts ~30 days.

**Do this on your laptop, not the Lightsail box.** You need a real Chrome window so Mom can see the OTP screen.

### 8.1 1mg
1. On laptop:
   ```bash
   cd /path/to/saathi
   uv run python scripts/manual_login_1mg.py
   ```
2. Chrome opens to 1mg. Hand the laptop to Mom. She enters her phone, gets OTP on her phone, types it.
3. Once logged in, **press Enter in the terminal** — the script saves `storage_state_1mg.json` next to the script.
4. Upload to Secrets Manager:
   ```bash
   aws secretsmanager create-secret \
     --name saathi/1mg/storage_state \
     --region ap-south-1 \
     --secret-string file://storage_state_1mg.json
   ```
5. **Delete the local file.** It contains her cookies. `rm storage_state_1mg.json`

### 8.2 PharmEasy (backup)
6. Same flow with `scripts/manual_login_pharmeasy.py`. Secret name: `saathi/pharmeasy/storage_state`.

### 8.3 Blinkit
7. Same flow with `scripts/manual_login_blinkit.py`. Secret name: `saathi/blinkit/storage_state`.

### 8.4 Calendar reminder
8. Set a recurring reminder in your calendar: **"Saathi: re-OTP all merchants"** every 30 days. When Saathi notifies you that a session expired, this is the playbook.

---

## 9 · Wire the Meta webhook (5 min, but ONLY after Lightsail is live)

1. Meta dashboard → **WhatsApp → Configuration → Webhook → Edit**.
2. **Callback URL:** `https://saathi.<your-domain>/webhook`
3. **Verify token:** the same string you put in `.env` as `WA_VERIFY_TOKEN`.
4. Click **Verify and save**. Meta will hit `GET /webhook` once. If your code is up, you'll see green.
5. **Subscribe to fields:**
   - ✅ `messages`
   - ✅ `message_template_status_update`
6. (Skip everything else for v1.)

---

## 10 · Telegram webhook for concierge confirmations (5 min)

1. From your laptop:
   ```bash
   curl -F "url=https://saathi.<your-domain>/telegram/webhook" \
        -F "secret_token=<TELEGRAM_WEBHOOK_SECRET from .env>" \
        "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook"
   ```
2. Verify: `curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"` → should show your URL.

---

## 11 · End-to-end smoke test (10 min)

The moment of truth.

### Day 1 acceptance — text echo
1. Mom sends `hello` from her WhatsApp to Saathi's number.
2. Within 5 seconds she receives: `नमस्ते मम्मी, मैं Saathi बोल रही हूँ`.
3. **If not:**
   - Check `sudo journalctl -u saathi -n 100` on the box.
   - If you see `webhook_bad_signature` → `WA_APP_SECRET` mismatch with what's in Meta dashboard.
   - If you see `webhook_dropped_sender` → `WA_MOM_NUMBER` in `.env` doesn't match Mom's actual number (check leading `+`).

### Day 2 acceptance — voice echo
4. Mom sends a Hindi voice note: *"नमस्ते Saathi, कैसी हो?"*
5. Within 6 seconds she gets a voice note back saying the same words.
6. **If not:**
   - `journalctl` for `stt_failed` or `tts_failed`.
   - Verify Sarvam credit balance > ₹0.
   - Verify the inbound voice note shows up at `s3://saathi-media-.../mom/inbound/`.

### Day 3 acceptance — first real medicine order
7. Mom voice-notes: *"टेलमा 40 खत्म हो गयी, please order करवा दो"*.
8. Within 30s she gets a voice asking for confirmation + 2 buttons.
9. She taps **हाँ** → order goes on 1mg COD → voice confirmation with order ID within 60s.
10. Verify the actual order arrives at her door within the ETA.

### Day 4 acceptance — grocery
11. Mom: *"दूध, ब्रेड, अंडे मंगवा दो"*. Cart voice within 45s. हाँ → COD on Blinkit.

### Day 5 acceptance — bill (concierge)
12. Mom: *"बिजली का बिल भर दो"*. Voice with amount within 30s. हाँ → you get a Telegram message.
13. You tap **Mark Paid** + attach receipt → Mom gets confirmation voice + image within 10s.

---

## 12 · After the smoke test passes — Day 7 ritual

1. Sit with Mom 60 min. Have her place all three orders unassisted while you watch silently. Don't help unless she's truly stuck.
2. Leave her alone for the afternoon. Watch CloudWatch logs, Telegram, S3 bucket.
3. Evening: top 3 fixes only. Don't refactor. Don't add features.
4. Tag the release: `git tag -a v1.0.0 -m "Saathi v1.0.0 — Mom-tested"` and push.
5. Call Mom and ask how her day was.

---

## 13 · Common breakages and fixes

| Symptom | Likely cause | Fix |
|---|---|---|
| Meta webhook verify keeps failing | `WA_VERIFY_TOKEN` mismatch, or 443 closed in Lightsail firewall | Re-check both; `sudo ss -tlnp \| grep 443` should show Caddy |
| `131047` error from Cloud API | 24h re-engagement window closed | Mom must message first, then you can reply free-form |
| 1mg redirects to /login during executor run | Cookie aged out (~30 days) | Re-run `scripts/manual_login_1mg.py`, re-upload secret |
| Browserbase: "concurrent session limit" | Free tier exhausted | Upgrade to Developer plan ($20/mo) |
| Bedrock: `AccessDeniedException` | Model access not approved yet | Bedrock console → Model access → ensure both Sonnet + Haiku are green |
| Sarvam returns empty transcripts | Audio not OGG/Opus, or expired URL | First 4 bytes of inbound audio should be `OggS`. URL from `download_media` is 5-min lived — call promptly |
| Bulbul mispronounces a brand | Add to `PRONUNCIATION_OVERRIDES` in `src/saathi/utils/hindi.py`; redeploy |
| Mom complains the bot is too slow | Pre-warm Browserbase + interim ack is missing | Day 6 polish item 1 + 7 |
| Telegram webhook silent | Wrong `secret_token` or wrong chat_id | `getWebhookInfo`; only Deep's chat_id is allowed |

---

## 14 · Where everything lives (memorize this)

| Thing | Location |
|---|---|
| Code | `~/saathi/` on Lightsail box, GitHub origin |
| Secrets at runtime | `.env` on the box, AWS Secrets Manager for storage states |
| Voice files | `s3://saathi-media-<suffix>/mom/...` |
| Mom's profile / orders / sessions | DynamoDB `saathi` table, `pk=mom, sk=...` |
| Logs | `sudo journalctl -u saathi`; or CloudWatch Logs (configure in Day 6+) |
| HTTPS cert | Caddy auto-managed, in `/var/lib/caddy/` |
| Mom's prescription images | S3 `mom/prescription/` |
| Bot phone number | Saathi SIM in your secondary handset |

---

## 15 · The "if everything blows up" emergency stop

```bash
ssh ubuntu@<lightsail-ip>
sudo systemctl stop saathi
```

Mom messaging the bot will get no response. That's the safe failure mode. WhatsApp won't show her an error — just no reply.

To bring it back: `sudo systemctl start saathi`.

To roll back to a prior commit:
```bash
cd ~/saathi
git log --oneline -10
git checkout <good-commit-sha>
sudo systemctl restart saathi
```

If you broke `.env`: there's no backup. That's why you keep a copy at `~/saathi-private/.env.backup` on your laptop. **Make that backup before §11.**

---

**That's everything.** When you've checked off §1 through §11, ping me ("setup done, ready for Day 7") and I'll resume the code track and we'll sit down for the Mom-uses-it-live session together.
