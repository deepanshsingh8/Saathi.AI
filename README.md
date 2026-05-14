# Saathi

> साथी — a WhatsApp voice-note assistant for Hindi-speaking parents.

Mom sends a voice note. Saathi orders her medicines, groceries, or pays a utility bill on her behalf. COD-only. No apps to install, no menus to navigate. Just WhatsApp.

## Status

**Pre-Day-1.** See `docs/STATUS.md` for current state.

## Documentation

- **`CLAUDE.md`** — instructions for Claude Code (project rules, stack, conventions)
- **`docs/PLAN.md`** — full strategy and architecture rationale
- **`docs/DAY_1.md` … `docs/DAY_7.md`** — per-day build briefs
- **`docs/STATUS.md`** — running state of the build
- **`docs/DECISIONS.md`** — architecture decision log

## Stack

Python 3.12 · FastAPI · Claude Sonnet 4.6 (Bedrock ap-south-1) · Sarvam Saaras + Bulbul · Playwright + Browserbase · DynamoDB · S3 · AWS Lightsail Mumbai · WhatsApp Cloud API · Telegram (concierge alerts).

## License

Personal-use project. Not licensed for commercial use or redistribution.
