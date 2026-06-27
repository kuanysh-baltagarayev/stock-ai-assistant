from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

import os


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env.example", override=False)


class ConfigurationError(ValueError):
    pass


class Settings(BaseModel):
    app_name: str = Field(default="Stock AI Assistant")
    database_url: str = Field(default="sqlite:///./stock_ai_assistant.db")
    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8000)
    allow_remote_api: bool = Field(default=False)
    openai_api_key: str | None = Field(default=None)
    openai_model: str = Field(default="gpt-4.1-mini")
    anthropic_api_key: str | None = Field(default=None)
    anthropic_model: str = Field(default="claude-haiku-4-5")
    llm_provider: str = Field(default="anthropic")
    llm_api_base_url: str | None = Field(default=None)
    deepseek_api_key: str | None = Field(default=None)
    fred_api_key: str | None = Field(default=None)
    alpha_vantage_api_key: str | None = Field(default=None)
    finnhub_api_key: str | None = Field(default=None)
    market_data_timeout_seconds: float = Field(default=20.0)
    market_data_max_attempts: int = Field(default=3)
    market_data_retry_backoff_seconds: float = Field(default=1.5)
    market_data_cache_ttl_seconds: int = Field(default=3600)
    provider_call_budget: int = Field(default=1000)
    openai_call_budget: int = Field(default=50)
    telegram_send_budget: int = Field(default=200)
    telegram_bot_token: str | None = Field(default=None)
    telegram_default_tickers: str = Field(
        default="AAPL,MSFT,NVDA,TSLA,AMD,AMZN,GOOGL,META"
    )
    telegram_allowed_chat_ids: list[int] = Field(default_factory=list)
    telegram_digest_interval_minutes: int = Field(default=1440)
    telegram_poll_timeout_seconds: int = Field(default=30)
    telegram_enabled: bool = Field(default=False)
    analysis_snapshot_retention_count: int = Field(default=50)
    analysis_snapshot_retention_days: int = Field(default=365)
    market_regime_enabled: bool = Field(default=False)


def resolve_database_url(database_url: str) -> str:
    if not database_url.startswith("sqlite:///"):
        return database_url

    raw_path = database_url.removeprefix("sqlite:///")
    if raw_path.startswith("/"):
        return database_url

    resolved_path = (PROJECT_ROOT / raw_path).resolve()
    return f"sqlite:///{resolved_path.as_posix()}"


def _parse_bool(value: str | None, *, env_name: str, default: bool) -> bool:
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(
        f"{env_name} must be a boolean value such as 1, 0, true, or false; got {value!r}."
    )


def _parse_int(
    value: str | None,
    *,
    env_name: str,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if value is None:
        return default

    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{env_name} must be an integer; got {value!r}.") from exc

    if minimum is not None and parsed < minimum:
        raise ConfigurationError(f"{env_name} must be >= {minimum}; got {parsed}.")
    if maximum is not None and parsed > maximum:
        raise ConfigurationError(f"{env_name} must be <= {maximum}; got {parsed}.")
    return parsed


def _parse_float(
    value: str | None,
    *,
    env_name: str,
    default: float,
    minimum: float | None = None,
) -> float:
    if value is None:
        return default

    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{env_name} must be a number; got {value!r}.") from exc

    if minimum is not None and parsed < minimum:
        raise ConfigurationError(f"{env_name} must be >= {minimum}; got {parsed}.")
    return parsed


def _parse_host(value: str | None) -> str:
    if value is None:
        return "127.0.0.1"

    host = value.strip()
    return host or "127.0.0.1"


def _parse_int_list(value: str | None, *, env_name: str) -> list[int]:
    if value is None:
        return []

    raw_items = [item.strip() for item in value.split(",")]
    parsed: list[int] = []
    seen: set[int] = set()
    for item in raw_items:
        if not item:
            continue
        try:
            chat_id = int(item)
        except ValueError as exc:
            raise ConfigurationError(f"{env_name} must contain comma-separated integers; got {value!r}.") from exc
        if chat_id not in seen:
            parsed.append(chat_id)
            seen.add(chat_id)
    return parsed


@lru_cache
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "Stock AI Assistant"),
        database_url=resolve_database_url(
            os.getenv("DATABASE_URL", "sqlite:///./stock_ai_assistant.db")
        ),
        api_host=_parse_host(os.getenv("APP_HOST")),
        api_port=_parse_int(
            os.getenv("APP_PORT"),
            env_name="APP_PORT",
            default=8000,
            minimum=1,
            maximum=65535,
        ),
        allow_remote_api=_parse_bool(
            os.getenv("ALLOW_REMOTE_API"),
            env_name="ALLOW_REMOTE_API",
            default=False,
        ),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5"),
        llm_provider=os.getenv("LLM_PROVIDER", "anthropic"),
        llm_api_base_url=os.getenv("LLM_API_BASE_URL") or None,
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY") or None,
        fred_api_key=os.getenv("FRED_API_KEY") or None,
        alpha_vantage_api_key=os.getenv("ALPHA_VANTAGE_API_KEY") or None,
        finnhub_api_key=os.getenv("FINNHUB_API_KEY") or None,
        market_data_timeout_seconds=_parse_float(
            os.getenv("MARKET_DATA_TIMEOUT_SECONDS"),
            env_name="MARKET_DATA_TIMEOUT_SECONDS",
            default=20.0,
            minimum=0.1,
        ),
        market_data_max_attempts=_parse_int(
            os.getenv("MARKET_DATA_MAX_ATTEMPTS"),
            env_name="MARKET_DATA_MAX_ATTEMPTS",
            default=3,
            minimum=1,
        ),
        market_data_retry_backoff_seconds=_parse_float(
            os.getenv("MARKET_DATA_RETRY_BACKOFF_SECONDS"),
            env_name="MARKET_DATA_RETRY_BACKOFF_SECONDS",
            default=1.5,
            minimum=0.0,
        ),
        market_data_cache_ttl_seconds=_parse_int(
            os.getenv("MARKET_DATA_CACHE_TTL_SECONDS"),
            env_name="MARKET_DATA_CACHE_TTL_SECONDS",
            default=3600,
            minimum=0,
        ),
        provider_call_budget=_parse_int(
            os.getenv("PROVIDER_CALL_BUDGET"),
            env_name="PROVIDER_CALL_BUDGET",
            default=1000,
            minimum=0,
        ),
        openai_call_budget=_parse_int(
            os.getenv("OPENAI_CALL_BUDGET"),
            env_name="OPENAI_CALL_BUDGET",
            default=50,
            minimum=0,
        ),
        telegram_send_budget=_parse_int(
            os.getenv("TELEGRAM_SEND_BUDGET"),
            env_name="TELEGRAM_SEND_BUDGET",
            default=200,
            minimum=0,
        ),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_default_tickers=os.getenv(
            "TELEGRAM_DEFAULT_TICKERS",
            "AAPL,MSFT,NVDA,TSLA,AMD,AMZN,GOOGL,META",
        ),
        telegram_allowed_chat_ids=_parse_int_list(
            os.getenv("TELEGRAM_ALLOWED_CHAT_IDS"),
            env_name="TELEGRAM_ALLOWED_CHAT_IDS",
        ),
        telegram_digest_interval_minutes=_parse_int(
            os.getenv("TELEGRAM_DIGEST_INTERVAL_MINUTES"),
            env_name="TELEGRAM_DIGEST_INTERVAL_MINUTES",
            default=1440,
            minimum=1,
        ),
        telegram_poll_timeout_seconds=_parse_int(
            os.getenv("TELEGRAM_POLL_TIMEOUT_SECONDS"),
            env_name="TELEGRAM_POLL_TIMEOUT_SECONDS",
            default=30,
            minimum=1,
        ),
        telegram_enabled=_parse_bool(
            os.getenv("TELEGRAM_ENABLED"),
            env_name="TELEGRAM_ENABLED",
            default=False,
        ),
        analysis_snapshot_retention_count=_parse_int(
            os.getenv("ANALYSIS_SNAPSHOT_RETENTION_COUNT"),
            env_name="ANALYSIS_SNAPSHOT_RETENTION_COUNT",
            default=50,
            minimum=1,
        ),
        analysis_snapshot_retention_days=_parse_int(
            os.getenv("ANALYSIS_SNAPSHOT_RETENTION_DAYS"),
            env_name="ANALYSIS_SNAPSHOT_RETENTION_DAYS",
            default=365,
            minimum=0,
        ),
        market_regime_enabled=_parse_bool(
            os.getenv("MARKET_REGIME_ENABLED"),
            env_name="MARKET_REGIME_ENABLED",
            default=False,
        ),
    )
