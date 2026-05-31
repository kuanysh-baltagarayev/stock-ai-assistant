from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from app.services.providers import provider_registry_payload


@dataclass(frozen=True)
class ProviderContract:
    name: str
    source_url: str | None
    source_tier: str | None
    data_category: str | None
    capability_list: list[str]
    legal_terms_note: str | None
    cache_ttl_seconds: int | None
    retry_attempts: int | None
    failure_taxonomy: list[str]

    @classmethod
    def from_name(cls, name: str) -> "ProviderContract":
        payload = provider_registry_payload(name)
        return cls.from_payload(name, payload)

    @classmethod
    def from_payload(cls, name: str, payload: dict[str, Any]) -> "ProviderContract":
        return cls(
            name=name,
            source_url=payload.get("source_url"),
            source_tier=payload.get("source_tier"),
            data_category=payload.get("data_category"),
            capability_list=list(payload.get("capability_list") or []),
            legal_terms_note=payload.get("legal_terms_note"),
            cache_ttl_seconds=_to_int(payload.get("cache_ttl_seconds")),
            retry_attempts=_to_int(payload.get("retry_attempts")),
            failure_taxonomy=list(payload.get("failure_taxonomy") or []),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_url": self.source_url,
            "source_tier": self.source_tier,
            "data_category": self.data_category,
            "capability_list": list(self.capability_list),
            "legal_terms_note": self.legal_terms_note,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "retry_attempts": self.retry_attempts,
            "failure_taxonomy": list(self.failure_taxonomy),
        }


@dataclass(frozen=True)
class MarketDataCollection:
    provider: ProviderContract
    ticker: str
    price: float
    currency: str | None
    history: pd.DataFrame
    info: dict[str, Any]
    price_source: str | None
    price_adjustment_policy: str | None
    corporate_actions_policy: str | None
    observed_at: datetime | None
    published_at: datetime | None
    fetched_at: datetime
    data_quality: dict[str, Any]
    fx: dict[str, Any] | None
    source_provenance: dict[str, Any]
    provider_name: str
    source_url: str | None
    source_tier: str | None
    data_category: str | None
    extraction_method: str | None
    parser_version: str | None
    cache_hit: bool = False

    def to_market_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "price": self.price,
            "currency": self.currency,
            "history": self.history.copy(deep=True),
            "info": dict(self.info),
            "provider_name": self.provider_name,
            "source_url": self.source_url,
            "source_tier": self.source_tier,
            "data_category": self.data_category,
            "extraction_method": self.extraction_method,
            "parser_version": self.parser_version,
            "observed_at": self.observed_at,
            "published_at": self.published_at,
            "fetched_at": self.fetched_at,
            "price_source": self.price_source,
            "price_adjustment_policy": self.price_adjustment_policy,
            "corporate_actions_policy": self.corporate_actions_policy,
            "data_quality": dict(self.data_quality),
            "fx": dict(self.fx) if isinstance(self.fx, dict) else None,
            "source_provenance": dict(self.source_provenance),
            "cache_hit": self.cache_hit,
        }


class MarketDataCollector(Protocol):
    def collect(self, symbol: str, *, settings: Any, provider_call_budget: int | None = None) -> MarketDataCollection:
        ...


def load_market_data_collection_fixture(path: str | Path) -> MarketDataCollection:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return market_data_collection_from_payload(payload)


def market_data_collection_from_payload(payload: dict[str, Any]) -> MarketDataCollection:
    provider_name = str(payload.get("provider_name") or "unknown")
    provider = ProviderContract.from_payload(provider_name, payload)
    return MarketDataCollection(
        provider=provider,
        ticker=_normalize_symbol(payload.get("ticker")),
        price=float(payload.get("price")),
        currency=payload.get("currency"),
        history=_history_from_payload(payload.get("history_rows") or []),
        info=dict(payload.get("info") or {}),
        price_source=payload.get("price_source"),
        price_adjustment_policy=payload.get("price_adjustment_policy"),
        corporate_actions_policy=payload.get("corporate_actions_policy"),
        observed_at=_parse_datetime(payload.get("observed_at")),
        published_at=_parse_datetime(payload.get("published_at")),
        fetched_at=_parse_datetime(payload.get("fetched_at")) or datetime.now(timezone.utc),
        data_quality=dict(payload.get("data_quality") or {}),
        fx=dict(payload["fx"]) if isinstance(payload.get("fx"), dict) else None,
        source_provenance=dict(payload.get("source_provenance") or {}),
        provider_name=provider_name,
        source_url=payload.get("source_url"),
        source_tier=payload.get("source_tier"),
        data_category=payload.get("data_category"),
        extraction_method=payload.get("extraction_method"),
        parser_version=payload.get("parser_version"),
        cache_hit=bool(payload.get("cache_hit", False)),
    )


def _history_from_payload(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt_value = value
    elif isinstance(value, str) and value.strip():
        parsed = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(parsed):
            return None
        dt_value = parsed.to_pydatetime()
    else:
        return None

    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=timezone.utc)
    return dt_value.astimezone(timezone.utc)


def _normalize_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    return symbol or "UNKNOWN"


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
