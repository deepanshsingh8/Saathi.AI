"""Runtime settings.

Day 1 fields only. Add to this as later days need them; do not pre-populate
empty placeholders for unused features (per docs/DAY_1.md Task 2).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # WhatsApp Cloud API
    WA_VERIFY_TOKEN: str = Field(..., description="Webhook verify string; matches Meta dashboard.")
    WA_APP_SECRET: str = Field(..., description="Meta app secret for X-Hub-Signature-256 HMAC.")
    WA_ACCESS_TOKEN: str = Field(..., description="System User token, messaging+management.")
    WA_PHONE_ID: str = Field(..., description="Phone Number ID from Meta API Setup panel.")
    WA_MOM_NUMBER: str = Field(..., description="Mom's E.164 number, only allowed sender.")

    # AWS
    AWS_REGION: str = "ap-south-1"
    DDB_TABLE: str = "saathi"
    S3_BUCKET: str = "saathi-media"

    # Day 2 — Sarvam speech
    SARVAM_API_KEY: str = ""
    TTS_VOICE: str = "vidya"
    STT_MODE: str = "codemix"

    # Day 3 — LLM (Bedrock primary, anthropic.com fallback)
    ANTHROPIC_API_KEY: str = ""
    BEDROCK_MODEL_SONNET: str = "anthropic.claude-sonnet-4-6-20260101"
    BEDROCK_MODEL_HAIKU: str = "anthropic.claude-haiku-4-5-20251001"
    USE_BEDROCK: bool = True
    LLM_MAX_TURNS: int = 12

    # Day 3 — Browserbase
    BROWSERBASE_API_KEY: str = ""
    BROWSERBASE_PROJECT_ID: str = ""

    # Day 3 — Telegram concierge alerts
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_DEEP_CHAT_ID: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""

    # Day 4 — Swiggy MCP (only used if SWIGGY_MCP_URL is non-empty)
    SWIGGY_MCP_URL: str = ""
    SWIGGY_CLIENT_ID: str = ""
    SWIGGY_CLIENT_SECRET: str = ""

    # Logging
    LOG_LEVEL: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
