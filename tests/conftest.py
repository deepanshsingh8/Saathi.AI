"""Shared test fixtures.

Sets the env vars Settings requires *before* any saathi.* import that touches
get_settings(). Keep this file fast — no real network, no real AWS.
"""
from __future__ import annotations

import os

# Day 1 required env. Real values come from .env in dev/prod.
os.environ.setdefault("WA_VERIFY_TOKEN", "test-verify-token")
os.environ.setdefault("WA_APP_SECRET", "test-app-secret")
os.environ.setdefault("WA_ACCESS_TOKEN", "test-access-token")
os.environ.setdefault("WA_PHONE_ID", "1234567890")
os.environ.setdefault("WA_MOM_NUMBER", "+919812345678")
os.environ.setdefault("AWS_REGION", "ap-south-1")
os.environ.setdefault("DDB_TABLE", "saathi-test")
os.environ.setdefault("S3_BUCKET", "saathi-media-test")
os.environ.setdefault("LOG_LEVEL", "WARNING")

# Day 2 — Sarvam (tests use mocks; key is just present so Settings validates)
os.environ.setdefault("SARVAM_API_KEY", "test-sarvam-key")
os.environ.setdefault("TTS_VOICE", "vidya")
os.environ.setdefault("STT_MODE", "codemix")

# Day 3 — LLM (force fallback path so AsyncAnthropicBedrock isn't constructed)
os.environ.setdefault("USE_BEDROCK", "false")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("BEDROCK_MODEL_SONNET", "anthropic.claude-sonnet-4-6-test")
os.environ.setdefault("BEDROCK_MODEL_HAIKU", "anthropic.claude-haiku-4-5-test")
os.environ.setdefault("LLM_MAX_TURNS", "4")

# Day 3 — Telegram (mocked in tests)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-tg-token")
os.environ.setdefault("TELEGRAM_DEEP_CHAT_ID", "12345")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-tg-secret")

# Day 3 — Browserbase (executors are patched in tests, so values just need to exist)
os.environ.setdefault("BROWSERBASE_API_KEY", "test-bb-key")
os.environ.setdefault("BROWSERBASE_PROJECT_ID", "test-bb-project")
