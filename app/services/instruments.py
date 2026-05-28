from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import InstrumentRegistry
from app.services.market_data import normalize_ticker


def upsert_instrument(
    db: Session,
    *,
    symbol: str,
    info: dict[str, Any],
    currency: str | None,
) -> InstrumentRegistry:
    normalized_symbol = normalize_ticker(symbol)
    payload = _build_registry_payload(normalized_symbol, info, currency=currency)
    instrument = (
        db.query(InstrumentRegistry)
        .filter(InstrumentRegistry.symbol == normalized_symbol)
        .one_or_none()
    )
    if instrument is None:
        instrument = InstrumentRegistry(symbol=normalized_symbol)
        db.add(instrument)

    for field, value in payload.items():
        setattr(instrument, field, value)

    db.commit()
    db.refresh(instrument)
    return instrument


def get_instrument_by_symbol(db: Session, symbol: str) -> InstrumentRegistry | None:
    normalized_symbol = normalize_ticker(symbol)
    return (
        db.query(InstrumentRegistry)
        .filter(InstrumentRegistry.symbol == normalized_symbol)
        .one_or_none()
    )


def _build_registry_payload(
    symbol: str,
    info: dict[str, Any],
    *,
    currency: str | None,
) -> dict[str, Any]:
    exchange = _first_non_empty(info.get("exchange"), info.get("fullExchangeName"))
    asset_type = _derive_asset_type(info)
    provider_aliases = _unique_strings(
        [
            symbol,
            info.get("symbol"),
            info.get("shortName"),
            info.get("longName"),
        ]
    )

    return {
        "provider_symbol": _first_non_empty(info.get("symbol"), symbol),
        "exchange_code": exchange,
        "mic": _first_non_empty(info.get("mic")),
        "country": _first_non_empty(info.get("country")),
        "timezone": _first_non_empty(info.get("exchangeTimezoneName")),
        "currency": _first_non_empty(currency, info.get("currency"), info.get("financialCurrency")),
        "asset_type": asset_type,
        "company_name": _first_non_empty(info.get("longName"), info.get("shortName")),
        "sector": _first_non_empty(info.get("sector")),
        "industry": _first_non_empty(info.get("industry")),
        "primary_listing": _first_non_empty(info.get("primaryExchange")),
        "isin": _first_non_empty(info.get("isin")),
        "figi": _first_non_empty(info.get("figi")),
        "provider_aliases": provider_aliases,
        "last_seen_at": datetime.now(timezone.utc),
    }


def _derive_asset_type(info: dict[str, Any]) -> str | None:
    quote_type = str(info.get("quoteType") or info.get("instrumentType") or "").upper()
    if not quote_type:
        return None
    if quote_type in {"EQUITY", "COMMON_STOCK"}:
        return "equity"
    if quote_type in {"ETF", "EXCHANGE_TRADED_FUND"}:
        return "etf"
    if quote_type in {"ADR", "AMERICAN_DEPOSITARY_RECEIPT"}:
        return "adr"
    if quote_type in {"INDEX", "INDEX_LIKE", "MUTUALFUND"}:
        return "index_like"
    if quote_type in {"CRYPTOCURRENCY", "CRYPTO"}:
        return "crypto_like"
    return "unsupported"


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _unique_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique
