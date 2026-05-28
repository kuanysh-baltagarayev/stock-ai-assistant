from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

import os


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env.example", override=False)


class Settings(BaseModel):
    app_name: str = Field(default="Stock AI Assistant")
    database_url: str = Field(default="sqlite:///./stock_ai_assistant.db")
    openai_api_key: str | None = Field(default=None)
    openai_model: str = Field(default="gpt-4.1-mini")
    telegram_bot_token: str | None = Field(default=None)
    telegram_default_tickers: str = Field(
        default="AAPL,MSFT,NVDA,TSLA,AMD,AMZN,GOOGL,META"
    )
    telegram_digest_interval_minutes: int = Field(default=1440)
    telegram_poll_timeout_seconds: int = Field(default=30)
    telegram_enabled: bool = Field(default=False)


@lru_cache
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "Stock AI Assistant"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./stock_ai_assistant.db"),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_default_tickers=os.getenv(
            "TELEGRAM_DEFAULT_TICKERS",
            "AAPL,MSFT,NVDA,TSLA,AMD,AMZN,GOOGL,META",
        ),
        telegram_digest_interval_minutes=int(
            os.getenv("TELEGRAM_DIGEST_INTERVAL_MINUTES", "1440")
        ),
        telegram_poll_timeout_seconds=int(
            os.getenv("TELEGRAM_POLL_TIMEOUT_SECONDS", "30")
        ),
        telegram_enabled=(os.getenv("TELEGRAM_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}),
    )
