from dataclasses import dataclass, field
from ipaddress import ip_address

from app.config import ConfigurationError, Settings


@dataclass(frozen=True)
class StartupDiagnostics:
    summary: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


def build_startup_diagnostics(settings: Settings) -> StartupDiagnostics:
    warnings: list[str] = []
    summary = {
        "app_name": settings.app_name,
        "api_host": settings.api_host,
        "api_port": str(settings.api_port),
        "database_scheme": _database_scheme(settings.database_url),
        "market_data_cache_ttl_seconds": str(settings.market_data_cache_ttl_seconds),
        "provider_call_budget": str(settings.provider_call_budget),
        "openai_call_budget": str(settings.openai_call_budget),
        "telegram_send_budget": str(settings.telegram_send_budget),
        "telegram_allowed_chat_ids": str(len(settings.telegram_allowed_chat_ids)),
        "analysis_snapshot_retention_count": str(
            settings.analysis_snapshot_retention_count
        ),
        "analysis_snapshot_retention_days": str(settings.analysis_snapshot_retention_days),
        "openai_enabled": str(bool(settings.openai_api_key)),
        "telegram_enabled": str(bool(settings.telegram_enabled and settings.telegram_bot_token)),
        "allow_remote_api": str(settings.allow_remote_api),
    }

    if settings.telegram_enabled and not settings.telegram_bot_token:
        warnings.append(
            "TELEGRAM_ENABLED is set but TELEGRAM_BOT_TOKEN is missing; Telegram bot startup will be skipped."
        )

    if settings.telegram_allowed_chat_ids:
        warnings.append(
            "Telegram access control is enabled; only chats listed in TELEGRAM_ALLOWED_CHAT_IDS can interact with the bot."
        )

    if not _is_loopback_host(settings.api_host):
        if settings.allow_remote_api:
            warnings.append(
                "API host is not loopback and remote API exposure is enabled; add auth, rate limits, CORS policy, and security headers before exposing it."
            )
        else:
            warnings.append(
                "API host is not loopback, but remote API exposure is disabled by policy; keep the service on localhost or enable ALLOW_REMOTE_API only after adding public-facing controls."
            )

    return StartupDiagnostics(summary=summary, warnings=tuple(warnings))


def enforce_local_api_policy(settings: Settings) -> None:
    if _is_loopback_host(settings.api_host):
        return
    if settings.allow_remote_api:
        return

    raise ConfigurationError(
        "Local-only API policy rejected a non-loopback APP_HOST. "
        "Keep APP_HOST on 127.0.0.1/localhost or set ALLOW_REMOTE_API=1 only after adding public-facing controls."
    )


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized in {"localhost", "127.0.0.1", "::1"}:
        return True

    try:
        address = ip_address(normalized)
    except ValueError:
        return False

    return address.is_loopback


def _database_scheme(database_url: str) -> str:
    return database_url.split(":", 1)[0] if ":" in database_url else database_url
