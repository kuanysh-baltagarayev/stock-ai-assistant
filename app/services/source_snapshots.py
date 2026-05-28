from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.models import SourceSnapshot


def upsert_source_snapshot(db: Session, *, market: dict[str, Any]) -> SourceSnapshot:
    payload = _build_snapshot_payload(market)
    content_hash = _content_hash(payload)
    snapshot = (
        db.query(SourceSnapshot)
        .filter(SourceSnapshot.content_hash == content_hash)
        .one_or_none()
    )
    if snapshot is None:
        snapshot = SourceSnapshot(
            ticker=_normalize_symbol(market.get("ticker")),
            provider_name=str(market.get("provider_name") or "yfinance"),
            content_hash=content_hash,
            payload=payload,
        )
        db.add(snapshot)

    snapshot.ticker = _normalize_symbol(market.get("ticker"))
    snapshot.provider_name = str(market.get("provider_name") or "yfinance")
    snapshot.source_url = market.get("source_url")
    snapshot.source_tier = market.get("source_tier")
    snapshot.data_category = market.get("data_category")
    snapshot.extraction_method = market.get("extraction_method")
    snapshot.parser_version = market.get("parser_version")
    snapshot.observed_at = _coerce_datetime(market.get("observed_at"))
    snapshot.published_at = _coerce_datetime(market.get("published_at"))
    snapshot.fetched_at = _coerce_datetime(market.get("fetched_at")) or datetime.now(
        timezone.utc
    )
    snapshot.confidence = _to_float(market.get("confidence"))
    snapshot.content_hash = content_hash
    snapshot.price_adjustment_policy = market.get("price_adjustment_policy")
    snapshot.payload = payload
    db.commit()
    db.refresh(snapshot)
    return snapshot


def _build_snapshot_payload(market: dict[str, Any]) -> dict[str, Any]:
    history = market.get("history")
    history_rows: list[dict[str, Any]] = []
    if isinstance(history, pd.DataFrame):
        history_rows = _serialize_history(history)

    return {
        "ticker": _normalize_symbol(market.get("ticker")),
        "provider_name": market.get("provider_name") or "yfinance",
        "source_url": market.get("source_url"),
        "source_tier": market.get("source_tier"),
        "data_category": market.get("data_category"),
        "extraction_method": market.get("extraction_method"),
        "parser_version": market.get("parser_version"),
        "observed_at": _dt_to_iso(market.get("observed_at")),
        "published_at": _dt_to_iso(market.get("published_at")),
        "fetched_at": _dt_to_iso(market.get("fetched_at")),
        "confidence": _to_float(market.get("confidence")),
        "price_adjustment_policy": market.get("price_adjustment_policy"),
        "price_source": market.get("price_source"),
        "currency": market.get("currency"),
        "price": _to_float(market.get("price")),
        "data_quality": market.get("data_quality"),
        "fx": market.get("fx"),
        "info": market.get("info") or {},
        "history_rows": history_rows,
    }


def _serialize_history(history: pd.DataFrame) -> list[dict[str, Any]]:
    records = history.reset_index().to_dict(orient="records")
    serialized: list[dict[str, Any]] = []
    for record in records:
        converted: dict[str, Any] = {}
        for key, value in record.items():
            converted[str(key)] = _json_safe(value)
        serialized.append(converted)
    return serialized


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return _dt_to_iso(value)
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    return value


def _content_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    return symbol or "UNKNOWN"


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    return None


def _dt_to_iso(value: Any) -> str | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
