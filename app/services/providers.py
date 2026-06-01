from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import ProviderRegistry


DEFAULT_PROVIDER_NAME = "yfinance"


def upsert_provider_registry(
    db: Session,
    *,
    name: str,
    source_url: str | None = None,
    source_tier: str | None = None,
    data_category: str | None = None,
    capability_list: list[str] | None = None,
    legal_terms_note: str | None = None,
    cache_ttl_seconds: int | None = None,
    retry_attempts: int | None = None,
    failure_taxonomy: list[str] | None = None,
) -> ProviderRegistry:
    provider = db.query(ProviderRegistry).filter(ProviderRegistry.name == name).one_or_none()
    if provider is None:
        provider = ProviderRegistry(name=name)
        db.add(provider)

    provider.source_url = source_url
    provider.source_tier = source_tier
    provider.data_category = data_category
    provider.capability_list = capability_list or []
    provider.legal_terms_note = legal_terms_note
    provider.cache_ttl_seconds = cache_ttl_seconds
    provider.retry_attempts = retry_attempts
    provider.failure_taxonomy = failure_taxonomy or []
    provider.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(provider)
    return provider


def record_provider_success(
    db: Session,
    *,
    name: str,
    source_url: str | None = None,
    source_tier: str | None = None,
    data_category: str | None = None,
    capability_list: list[str] | None = None,
    legal_terms_note: str | None = None,
    cache_ttl_seconds: int | None = None,
    retry_attempts: int | None = None,
    failure_taxonomy: list[str] | None = None,
) -> ProviderRegistry:
    provider = upsert_provider_registry(
        db,
        name=name,
        source_url=source_url,
        source_tier=source_tier,
        data_category=data_category,
        capability_list=capability_list,
        legal_terms_note=legal_terms_note,
        cache_ttl_seconds=cache_ttl_seconds,
        retry_attempts=retry_attempts,
        failure_taxonomy=failure_taxonomy,
    )
    provider.last_success_at = datetime.now(timezone.utc)
    provider.last_failure_at = None
    provider.last_failure_mode = None
    db.commit()
    db.refresh(provider)
    return provider


def record_provider_failure(
    db: Session,
    *,
    name: str,
    failure_mode: str,
    source_url: str | None = None,
    source_tier: str | None = None,
    data_category: str | None = None,
    capability_list: list[str] | None = None,
    legal_terms_note: str | None = None,
    cache_ttl_seconds: int | None = None,
    retry_attempts: int | None = None,
    failure_taxonomy: list[str] | None = None,
) -> ProviderRegistry:
    provider = upsert_provider_registry(
        db,
        name=name,
        source_url=source_url,
        source_tier=source_tier,
        data_category=data_category,
        capability_list=capability_list,
        legal_terms_note=legal_terms_note,
        cache_ttl_seconds=cache_ttl_seconds,
        retry_attempts=retry_attempts,
        failure_taxonomy=failure_taxonomy,
    )
    provider.last_failure_at = datetime.now(timezone.utc)
    provider.last_failure_mode = failure_mode
    db.commit()
    db.refresh(provider)
    return provider


def get_provider_by_name(db: Session, name: str) -> ProviderRegistry | None:
    return db.query(ProviderRegistry).filter(ProviderRegistry.name == name).one_or_none()


def list_providers(db: Session) -> list[ProviderRegistry]:
    return db.query(ProviderRegistry).order_by(ProviderRegistry.name.asc()).all()


def provider_registry_payload(name: str) -> dict[str, Any]:
    if name == DEFAULT_PROVIDER_NAME:
        return {
            "source_url": "https://github.com/ranaroussi/yfinance",
            "source_tier": "Tier 2",
            "data_category": "market_data",
            "capability_list": [
                "historical_prices",
                "company_profile",
                "fast_info",
            ],
            "legal_terms_note": "Respect upstream terms and rate limits; no login bypass.",
            "cache_ttl_seconds": 3600,
            "retry_attempts": 3,
            "failure_taxonomy": [
                "unavailable",
                "stale",
                "rate_limited",
                "parse_failed",
                "disagreement",
            ],
        }

    if name == "alpha_vantage":
        return {
            "source_url": "https://www.alphavantage.co",
            "source_tier": "Tier 2",
            "data_category": "market_data",
            "capability_list": [
                "historical_prices",
            ],
            "legal_terms_note": (
                "Free-tier daily data via API key (ALPHA_VANTAGE_API_KEY). "
                "Respect the free-tier request limits and upstream terms."
            ),
            "cache_ttl_seconds": 3600,
            "retry_attempts": 2,
            "failure_taxonomy": [
                "unavailable",
                "stale",
                "rate_limited",
                "parse_failed",
            ],
        }

    if name == "edgar":
        return {
            "source_url": "https://www.sec.gov/cgi-bin/browse-edgar",
            "source_tier": "Tier 1",
            "data_category": "sec_filings",
            "capability_list": [
                "sec_8k",
                "sec_10q",
                "sec_10k",
                "sec_def14a",
                "company_cik_lookup",
            ],
            "legal_terms_note": (
                "Public U.S. government data; free to access. "
                "Respect EDGAR rate limits (~10 req/s per IP). "
                "Include User-Agent header per EDGAR policy."
            ),
            "cache_ttl_seconds": 3600,
            "retry_attempts": 2,
            "failure_taxonomy": [
                "unavailable",
                "rate_limited",
                "parse_failed",
                "ticker_not_found",
            ],
        }

    return {
        "source_url": None,
        "source_tier": None,
        "data_category": None,
        "capability_list": [],
        "legal_terms_note": None,
        "cache_ttl_seconds": None,
        "retry_attempts": None,
        "failure_taxonomy": [],
    }
