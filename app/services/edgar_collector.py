"""SEC EDGAR filing collector.

Uses two public EDGAR endpoints (free, no auth required):
  - /files/company_tickers.json  — static ticker-to-CIK map
  - /submissions/CIK{cik}.json  — recent filings list

EDGAR enforces a soft rate limit of ~10 requests per second per IP.
The CIK map is fetched once and cached in-memory for the process lifetime.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from urllib import request

logger = logging.getLogger(__name__)

_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_FILING_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/index.json"
_SEC_FILING_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=5&search_text="

EDGAR_PROVIDER_NAME = "edgar"
EDGAR_SOURCE_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
EDGAR_SOURCE_TIER = "Tier 1"
EDGAR_DATA_CATEGORY = "sec_filings"
EDGAR_PARSER_VERSION = "edgar-collector-v1"
EDGAR_TIMEOUT_SECONDS = 15

_RELEVANT_FORMS = {"8-K", "10-Q", "10-K", "10-K/A", "10-Q/A", "8-K/A", "DEF 14A", "S-1"}

_cik_map_lock = Lock()
_cik_map_cache: dict[str, int] | None = None


@dataclass(frozen=True)
class EdgarFiling:
    form_type: str
    filing_date: str
    accession_number: str
    description: str
    sec_url: str


@dataclass
class EdgarCollection:
    ticker: str
    cik: int | None
    company_name: str | None
    filings: list[EdgarFiling]
    fetched_at: datetime
    provider_name: str = EDGAR_PROVIDER_NAME
    source_url: str = EDGAR_SOURCE_URL
    source_tier: str = EDGAR_SOURCE_TIER
    data_category: str = EDGAR_DATA_CATEGORY
    parser_version: str = EDGAR_PARSER_VERSION
    error: str | None = None

    def to_snapshot_payload(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "cik": self.cik,
            "company_name": self.company_name,
            "filings": [
                {
                    "form_type": f.form_type,
                    "filing_date": f.filing_date,
                    "accession_number": f.accession_number,
                    "description": f.description,
                    "sec_url": f.sec_url,
                }
                for f in self.filings
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
            "ticker": self.ticker,
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


def fetch_recent_filings(
    ticker: str,
    *,
    max_count: int = 8,
    forms: set[str] | None = None,
    timeout: int = EDGAR_TIMEOUT_SECONDS,
) -> EdgarCollection:
    """Fetch recent SEC EDGAR filings for a ticker.

    Returns an EdgarCollection; on network errors the collection has an error
    field set and an empty filings list — callers should not raise on this.
    """
    symbol = ticker.strip().upper()
    fetched_at = datetime.now(timezone.utc)
    selected_forms = forms if forms is not None else _RELEVANT_FORMS

    try:
        cik_map = _get_cik_map(timeout=timeout)
    except Exception as exc:
        logger.warning(
            "edgar_cik_map_fetch_failed",
            extra={"component": "edgar", "ticker": symbol, "error": str(exc)},
        )
        return EdgarCollection(
            ticker=symbol,
            cik=None,
            company_name=None,
            filings=[],
            fetched_at=fetched_at,
            error=f"CIK map unavailable: {exc}",
        )

    cik = cik_map.get(symbol)
    if cik is None:
        return EdgarCollection(
            ticker=symbol,
            cik=None,
            company_name=None,
            filings=[],
            fetched_at=fetched_at,
            error=f"Ticker {symbol!r} not found in EDGAR CIK map",
        )

    try:
        submissions = _fetch_submissions(cik, timeout=timeout)
    except Exception as exc:
        logger.warning(
            "edgar_submissions_fetch_failed",
            extra={"component": "edgar", "ticker": symbol, "cik": cik, "error": str(exc)},
        )
        return EdgarCollection(
            ticker=symbol,
            cik=cik,
            company_name=None,
            filings=[],
            fetched_at=fetched_at,
            error=f"EDGAR submissions unavailable: {exc}",
        )

    company_name = submissions.get("name")
    recent = submissions.get("filings", {}).get("recent", {})
    filings = _parse_filings(cik, recent, selected_forms=selected_forms, max_count=max_count)

    logger.info(
        "edgar_filings_fetched",
        extra={
            "component": "edgar",
            "ticker": symbol,
            "cik": cik,
            "filing_count": len(filings),
        },
    )
    return EdgarCollection(
        ticker=symbol,
        cik=cik,
        company_name=company_name,
        filings=filings,
        fetched_at=fetched_at,
    )


def edgar_collection_from_payload(payload: dict[str, Any]) -> EdgarCollection:
    """Reconstruct an EdgarCollection from a stored payload dict (for fixtures/tests)."""
    fetched_at_raw = payload.get("fetched_at")
    if isinstance(fetched_at_raw, str):
        fetched_at = datetime.fromisoformat(fetched_at_raw)
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    else:
        fetched_at = datetime.now(timezone.utc)

    filings = [
        EdgarFiling(
            form_type=f["form_type"],
            filing_date=f["filing_date"],
            accession_number=f["accession_number"],
            description=f["description"],
            sec_url=f["sec_url"],
        )
        for f in (payload.get("filings") or [])
    ]
    return EdgarCollection(
        ticker=str(payload.get("ticker") or "UNKNOWN"),
        cik=payload.get("cik"),
        company_name=payload.get("company_name"),
        filings=filings,
        fetched_at=fetched_at,
        provider_name=payload.get("provider_name", EDGAR_PROVIDER_NAME),
        source_url=payload.get("source_url", EDGAR_SOURCE_URL),
        source_tier=payload.get("source_tier", EDGAR_SOURCE_TIER),
        data_category=payload.get("data_category", EDGAR_DATA_CATEGORY),
        parser_version=payload.get("parser_version", EDGAR_PARSER_VERSION),
        error=payload.get("error"),
    )


def _get_cik_map(*, timeout: int = EDGAR_TIMEOUT_SECONDS) -> dict[str, int]:
    global _cik_map_cache
    with _cik_map_lock:
        if _cik_map_cache is not None:
            return _cik_map_cache
        data = _http_get_json(_COMPANY_TICKERS_URL, timeout=timeout)
        mapping: dict[str, int] = {}
        for entry in data.values():
            ticker_val = str(entry.get("ticker") or "").strip().upper()
            cik_val = entry.get("cik_str")
            if ticker_val and cik_val is not None:
                mapping[ticker_val] = int(cik_val)
        _cik_map_cache = mapping
        return _cik_map_cache


def _fetch_submissions(cik: int, *, timeout: int) -> dict[str, Any]:
    url = _SUBMISSIONS_URL.format(cik=cik)
    return _http_get_json(url, timeout=timeout)


def _parse_filings(
    cik: int,
    recent: dict[str, Any],
    *,
    selected_forms: set[str],
    max_count: int,
) -> list[EdgarFiling]:
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accessions = recent.get("accessionNumber") or []
    descriptions = recent.get("primaryDocDescription") or []
    primary_docs = recent.get("primaryDocument") or []

    filings: list[EdgarFiling] = []
    for form, date, acc, desc, doc in zip(forms, dates, accessions, descriptions, primary_docs):
        if form not in selected_forms:
            continue
        clean_acc = acc.replace("-", "")
        doc_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{clean_acc}/{doc}"
            if doc
            else f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik:010d}&type={form}&dateb=&owner=include&count=5"
        )
        filings.append(
            EdgarFiling(
                form_type=str(form),
                filing_date=str(date),
                accession_number=str(acc),
                description=str(desc) if desc else form,
                sec_url=doc_url,
            )
        )
        if len(filings) >= max_count:
            break
    return filings


def _http_get_json(url: str, *, timeout: int) -> Any:
    req = request.Request(
        url,
        headers={"User-Agent": "stock-ai-assistant research@example.com"},
    )
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def reset_cik_map_cache() -> None:
    """Reset the in-memory CIK map cache (used in tests)."""
    global _cik_map_cache
    with _cik_map_lock:
        _cik_map_cache = None
