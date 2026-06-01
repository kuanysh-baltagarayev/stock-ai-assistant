"""Federal Reserve Economic Data (FRED) collector.

Uses FRED API to fetch key macroeconomic indicators.
Requires FRED_API_KEY from https://fred.stlouisfed.org/docs/api/

If no API key is configured, returns a collection with no data (not an error).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib import request

logger = logging.getLogger(__name__)

_FRED_API_BASE = "https://api.stlouisfed.org/fred/series/observations"
_FRED_SERIES = {
    "FEDFUNDS": "Federal Funds Effective Rate (%)",
    "UNRATE": "Unemployment Rate (%)",
    "CPIAUCSL": "Consumer Price Index (all-urban)",
    "PAYEMS": "Total Nonfarm Payroll (thousands)",
    "DEXUSEU": "USD/EUR Exchange Rate",
}

FRED_PROVIDER_NAME = "fred"
FRED_SOURCE_URL = "https://fred.stlouisfed.org"
FRED_SOURCE_TIER = "Tier 1"
FRED_DATA_CATEGORY = "macro_indicators"
FRED_PARSER_VERSION = "fred-collector-v1"
FRED_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class FredObservation:
    date: str
    value: float | None
    series_id: str
    series_name: str


@dataclass
class FredCollection:
    observations: list[FredObservation]
    fetched_at: datetime
    provider_name: str = FRED_PROVIDER_NAME
    source_url: str = FRED_SOURCE_URL
    source_tier: str = FRED_SOURCE_TIER
    data_category: str = FRED_DATA_CATEGORY
    parser_version: str = FRED_PARSER_VERSION
    error: str | None = None

    def to_snapshot_payload(self) -> dict[str, Any]:
        return {
            "observations": [
                {
                    "date": o.date,
                    "value": o.value,
                    "series_id": o.series_id,
                    "series_name": o.series_name,
                }
                for o in self.observations
            ],
            "fetched_at": self.fetched_at.isoformat(),
            "provider_name": self.provider_name,
            "source_url": self.source_url,
            "source_tier": self.source_tier,
            "data_category": self.data_category,
            "parser_version": self.parser_version,
            "error": self.error,
        }

    def as_source_snapshot_dict(self) -> dict[str, Any]:
        payload = self.to_snapshot_payload()
        return {
            "ticker": "MACRO",
            "provider_name": self.provider_name,
            "source_url": self.source_url,
            "source_tier": self.source_tier,
            "data_category": self.data_category,
            "extraction_method": "api",
            "parser_version": self.parser_version,
            "observed_at": self.fetched_at,
            "published_at": None,
            "fetched_at": self.fetched_at,
            "confidence": 1.0 if not self.error else 0.0,
            "price_adjustment_policy": None,
            "price": None,
            "currency": None,
            "data_quality": {"summary": "ok" if not self.error else f"error: {self.error}"},
            "fx": None,
            "info": {},
            "history": None,
            "source_provenance": {
                "provider_name": self.provider_name,
                "source_url": self.source_url,
                "source_tier": self.source_tier,
                "data_category": self.data_category,
            },
            "payload_extra": payload,
        }


def fetch_macro_indicators(
    api_key: str | None = None,
    *,
    timeout: int = FRED_TIMEOUT_SECONDS,
) -> FredCollection:
    """Fetch recent macroeconomic indicators from FRED.

    Returns a FredCollection; on network errors or missing API key,
    collection has an error field set and empty observations — callers
    should not raise on this.
    """
    fetched_at = datetime.now(timezone.utc)

    if not api_key:
        logger.debug(
            "fred_api_key_missing",
            extra={"component": "fred"},
        )
        return FredCollection(
            observations=[],
            fetched_at=fetched_at,
            error="FRED_API_KEY not configured",
        )

    observations: list[FredObservation] = []
    errors: list[str] = []

    for series_id, series_name in _FRED_SERIES.items():
        try:
            obs = _fetch_series_latest(series_id, series_name, api_key, timeout=timeout)
            observations.extend(obs)
        except Exception as exc:
            logger.warning(
                "fred_series_fetch_failed",
                extra={"component": "fred", "series_id": series_id, "error": str(exc)},
            )
            errors.append(f"{series_id}: {str(exc)}")

    if not observations and errors:
        error_msg = "; ".join(errors[:2])
        return FredCollection(
            observations=[],
            fetched_at=fetched_at,
            error=f"Failed to fetch indicators: {error_msg}",
        )

    logger.info(
        "fred_indicators_fetched",
        extra={
            "component": "fred",
            "observation_count": len(observations),
            "error_count": len(errors),
        },
    )
    return FredCollection(
        observations=observations,
        fetched_at=fetched_at,
        error="; ".join(errors) if errors else None,
    )


def _fetch_series_latest(
    series_id: str,
    series_name: str,
    api_key: str,
    *,
    timeout: int,
) -> list[FredObservation]:
    """Fetch the latest observation for a FRED series."""
    url = (
        f"{_FRED_API_BASE}?"
        f"series_id={series_id}&"
        f"api_key={api_key}&"
        f"file_type=json&"
        f"limit=1&"
        f"sort_order=desc"
    )
    try:
        data = _http_get_json(url, timeout=timeout)
    except Exception as exc:
        logger.warning(
            "fred_http_error",
            extra={"component": "fred", "series_id": series_id, "error": str(exc)},
        )
        raise

    observations: list[FredObservation] = []
    for obs in data.get("observations", []):
        date_val = obs.get("date")
        value_val = obs.get("value")
        if date_val and value_val and value_val != ".":
            try:
                observations.append(
                    FredObservation(
                        date=str(date_val),
                        value=float(value_val),
                        series_id=series_id,
                        series_name=series_name,
                    )
                )
            except (ValueError, TypeError):
                pass

    return observations


def _http_get_json(url: str, *, timeout: int) -> Any:
    req = request.Request(
        url,
        headers={"User-Agent": "stock-ai-assistant research@example.com"},
    )
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))
