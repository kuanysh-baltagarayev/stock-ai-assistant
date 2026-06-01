from datetime import datetime, timedelta, timezone
import logging
from zoneinfo import ZoneInfo
from typing import Any

from sqlalchemy.orm import Session

from app.models import AnalysisSnapshot
from app.schemas import (
    AnalyzeResponse,
    DataQualityFlags,
    FXNormalization,
    MarketSession,
    ScanError,
    ScanResponse,
    ScanResult,
    ScanSummary,
    SourceProvenance,
)
from app.services.ai_explainer import explain_analysis, rule_based_explanation
from app.services.edgar_collector import fetch_recent_filings
from app.services.economic_calendar import upcoming_events
from app.services.exchange_calendar import get_session_state, next_trading_day
from app.services.fred_collector import fetch_macro_indicators
from app.services.instruments import upsert_instrument
from app.services.history import cleanup_old_snapshots
from app.services.indicators import calculate_indicators
from app.config import get_settings
from app.services.market_data import (
    MarketDataError,
    extract_fundamentals,
    get_market_data,
)
from app.services.source_snapshots import upsert_source_snapshot
from app.services.scoring import score_stock


logger = logging.getLogger(__name__)


def analyze_ticker(
    ticker: str,
    db: Session | None = None,
    use_ai_explanation: bool = True,
) -> AnalyzeResponse:
    logger.debug("analysis_started", extra={"component": "scanner", "ticker": ticker})
    market = get_market_data(ticker, db=db)
    if db is not None:
        _save_source_snapshot(db, market)
        _save_edgar_filings(db, market["ticker"])
        _save_macro_indicators(db)
    fundamentals = extract_fundamentals(market["info"])
    technicals = calculate_indicators(market["history"])
    scoring = score_stock(market["price"], technicals, fundamentals)
    if db is not None:
        _save_instrument(db, market["ticker"], market["info"], market["currency"])
    settings = get_settings()
    market_session = _build_market_session(market)

    payload = {
        "ticker": market["ticker"],
        "generated_at": datetime.now(timezone.utc),
        "price": market["price"],
        "currency": market["currency"],
        "price_adjustment_policy": market.get("price_adjustment_policy"),
        "fundamentals": fundamentals.model_dump(),
        "technicals": technicals.model_dump(),
        "scores": scoring.scores.model_dump(),
        "recommendation": scoring.recommendation,
        "short_reason": scoring.short_reason,
        "source_provenance": _build_source_provenance(market),
        "data_quality": _build_data_quality(market),
        "fx": _build_fx_normalization(market),
        "market_session": market_session,
        "event_calendar": market.get("event_calendar"),
    }

    if use_ai_explanation:
        explanation = explain_analysis(_json_ready(payload), scoring.reasons)
    else:
        explanation = rule_based_explanation(_json_ready(payload), scoring.reasons)

    response = AnalyzeResponse(
        **payload,
        explanation=explanation,
        operation_notes=_build_operation_notes(
            market=market,
            explanation=explanation,
            settings=settings,
            used_ai_explanation=use_ai_explanation,
            market_session=market_session,
            event_calendar=market.get("event_calendar"),
        ),
    )
    if db is not None:
        _save_snapshot(db, response)
    logger.debug(
        "analysis_completed",
        extra={
            "component": "scanner",
            "ticker": response.ticker,
            "final_score": response.scores.final_score,
            "recommendation": response.recommendation,
        },
    )
    return response


def scan_tickers(tickers: list[str], db: Session | None = None) -> ScanResponse:
    results: list[ScanResult] = []
    errors: list[ScanError] = []
    notes: list[str] = []

    logger.info(
        "scan_started",
        extra={"component": "scanner", "ticker_count": len(tickers), "persisting": db is not None},
    )

    for ticker in tickers:
        try:
            analysis = analyze_ticker(ticker, db=db, use_ai_explanation=False)
        except MarketDataError as exc:
            errors.append(ScanError(ticker=ticker, error=str(exc)))
            logger.warning(
                "scan_ticker_failed",
                extra={"component": "scanner", "ticker": ticker, "error": str(exc)},
            )
            continue
        except Exception as exc:
            errors.append(ScanError(ticker=ticker, error=f"Unexpected error: {exc}"))
            logger.exception(
                "scan_ticker_unexpected_failure",
                extra={"component": "scanner", "ticker": ticker},
            )
            continue

        results.append(
            ScanResult(
                ticker=analysis.ticker,
                price=analysis.price,
                final_score=analysis.scores.final_score,
                momentum_score=analysis.scores.momentum_score,
                valuation_score=analysis.scores.valuation_score,
                risk_score=analysis.scores.risk_score,
                confidence=getattr(getattr(analysis, "data_quality", None), "confidence", None)
                if getattr(analysis, "data_quality", None) is not None
                else None,
                recommendation=analysis.recommendation,
                short_reason=analysis.short_reason,
            )
        )
        notes.extend(_event_calendar_notes(analysis.ticker, analysis.event_calendar))

    results.sort(key=lambda item: item.final_score, reverse=True)
    summary = _build_scan_summary(tickers=tickers, results=results, errors=errors, notes=notes)

    if summary.partial_failure:
        logger.warning(
            "scan_partial_failure",
            extra={
                "component": "scanner",
                "ticker_count": len(tickers),
                "result_count": len(results),
                "error_count": len(errors),
                "failed_tickers": summary.failed_tickers,
            },
        )
    logger.info(
        "scan_finished",
        extra={
            "component": "scanner",
            "ticker_count": len(tickers),
            "result_count": len(results),
            "error_count": len(errors),
            "partial_failure": summary.partial_failure,
        },
    )
    return ScanResponse(results=results, errors=errors, summary=summary)


def _save_snapshot(db: Session, response: AnalyzeResponse) -> None:
    snapshot = AnalysisSnapshot(
        ticker=response.ticker,
        company_name=response.fundamentals.company_name,
        price=response.price,
        final_score=response.scores.final_score,
        recommendation=response.recommendation,
        payload=response.model_dump(mode="json"),
    )
    try:
        db.add(snapshot)
        db.commit()
        logger.info(
            "analysis_snapshot_saved",
            extra={
                "component": "persistence",
                "ticker": response.ticker,
                "final_score": response.scores.final_score,
                "recommendation": response.recommendation,
            },
        )
    except Exception:
        db.rollback()
        logger.exception(
            "analysis_snapshot_persist_failed",
            extra={"component": "persistence", "ticker": response.ticker},
        )
        return

    settings = get_settings()
    try:
        deleted_count = cleanup_old_snapshots(
            db,
            retention_count=settings.analysis_snapshot_retention_count,
            retention_days=settings.analysis_snapshot_retention_days,
        )
    except Exception:
        logger.exception(
            "analysis_snapshot_retention_cleanup_failed",
            extra={"component": "persistence", "ticker": response.ticker},
        )
        return

    if deleted_count:
        logger.info(
            "analysis_snapshot_retention_cleanup",
            extra={
                "component": "persistence",
                "ticker": response.ticker,
                "retention_deleted_count": deleted_count,
            },
        )


def _save_instrument(db: Session, symbol: str, info: dict, currency: str | None) -> None:
    try:
        instrument = upsert_instrument(db, symbol=symbol, info=info, currency=currency)
    except Exception:
        logger.exception(
            "instrument_registry_upsert_failed",
            extra={"component": "persistence", "ticker": symbol},
        )
        return

    logger.info(
        "instrument_registry_saved",
        extra={
            "component": "persistence",
            "ticker": symbol,
            "asset_type": instrument.asset_type,
            "exchange_code": instrument.exchange_code,
            "currency": instrument.currency,
        },
    )


def _save_source_snapshot(db: Session, market: dict) -> None:
    try:
        snapshot = upsert_source_snapshot(db, market=market)
    except Exception:
        logger.exception(
            "source_snapshot_persist_failed",
            extra={"component": "persistence", "ticker": market.get("ticker")},
        )
        return

    logger.info(
        "source_snapshot_saved",
        extra={
            "component": "persistence",
            "ticker": snapshot.ticker,
            "provider_name": snapshot.provider_name,
            "source_tier": snapshot.source_tier,
        },
    )


def _json_ready(payload: dict) -> dict:
    converted = payload.copy()
    generated_at = converted.get("generated_at")
    if isinstance(generated_at, datetime):
        converted["generated_at"] = generated_at.isoformat()
    return converted


def _build_source_provenance(market: dict) -> dict:
    provenance = market.get("source_provenance") or {}
    return SourceProvenance(
        provider_name=provenance.get("provider_name") or market.get("provider_name") or "yfinance",
        source_url=provenance.get("source_url") or market.get("source_url"),
        source_tier=provenance.get("source_tier") or market.get("source_tier"),
        data_category=provenance.get("data_category") or market.get("data_category"),
        extraction_method=provenance.get("extraction_method") or market.get("extraction_method"),
        parser_version=provenance.get("parser_version") or market.get("parser_version"),
        observed_at=provenance.get("observed_at") or market.get("observed_at"),
        published_at=provenance.get("published_at") or market.get("published_at"),
        fetched_at=provenance.get("fetched_at") or market.get("fetched_at"),
        confidence=provenance.get("confidence") or market.get("data_quality", {}).get("confidence"),
        content_hash=provenance.get("content_hash"),
    ).model_dump(mode="json")


def _build_data_quality(market: dict) -> dict:
    data_quality = market.get("data_quality") or {}
    return DataQualityFlags(
        stale=bool(data_quality.get("stale", False)),
        delayed=bool(data_quality.get("delayed", False)),
        estimated=bool(data_quality.get("estimated", False)),
        missing=bool(data_quality.get("missing", False)),
        source_disagreed=bool(data_quality.get("source_disagreed", False)),
        confidence=float(data_quality.get("confidence", 1.0)),
        summary=data_quality.get("summary"),
    ).model_dump(mode="json")


def _build_fx_normalization(market: dict) -> dict | None:
    fx = market.get("fx")
    if not fx:
        return None

    return FXNormalization(
        base_currency=fx.get("base_currency"),
        quote_currency=fx.get("quote_currency"),
        fx_rate_to_usd=fx.get("fx_rate_to_usd"),
        fx_source=fx.get("fx_source"),
        fx_timestamp=fx.get("fx_timestamp"),
        fx_assumption_note=fx.get("fx_assumption_note"),
    ).model_dump(mode="json")


def _build_market_session(market: dict) -> dict | None:
    reference_time = market.get("fetched_at") or market.get("observed_at") or datetime.now(timezone.utc)
    if not isinstance(reference_time, datetime):
        return None
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)

    timezone_name = (
        market.get("info", {}).get("exchangeTimezoneName")
        or market.get("info", {}).get("timezone")
        or market.get("timezone")
        or "America/New_York"
    )
    try:
        zone = ZoneInfo(str(timezone_name))
    except Exception:
        timezone_name = "America/New_York"
        zone = ZoneInfo(timezone_name)

    local_reference = reference_time.astimezone(zone)
    market_open_at, market_close_at, status = _session_window(local_reference)
    is_open = status == "open"
    session_state = get_session_state(local_reference)

    freshness_state = "fresh"
    freshness_note = None
    history_timestamp = market.get("published_at") or market.get("observed_at")
    if isinstance(history_timestamp, datetime):
        if history_timestamp.tzinfo is None:
            history_timestamp = history_timestamp.replace(tzinfo=timezone.utc)
        history_local = history_timestamp.astimezone(zone)
        if not is_open:
            freshness_state = "session_closed"
            status_detail = _session_status_detail(session_state)
            freshness_note = (
                f"Market session is {status}{status_detail}; latest bar is from {history_local.date().isoformat()}."
            )
        elif history_local.date() < local_reference.date():
            freshness_state = "stale"
            freshness_note = (
                "Market session is open, but the latest bar is from a prior trading day."
            )
    elif not is_open:
        freshness_state = "session_closed"
        status_detail = _session_status_detail(session_state)
        freshness_note = f"Market session is {status}{status_detail}; fresh intraday coverage may be delayed."

    return MarketSession(
        timezone=timezone_name,
        reference_time=local_reference,
        status=status,
        is_open=is_open,
        market_open_at=market_open_at,
        market_close_at=market_close_at,
        freshness_state=freshness_state,
        freshness_note=freshness_note,
    ).model_dump(mode="json")


def _session_status_detail(session_state: str) -> str:
    """Return a detail string for the session state to append to status messages."""
    if session_state == "holiday":
        return " (NYSE holiday)"
    elif session_state == "early_close":
        return " (early close at 13:00 ET)"
    return ""


def _session_window(local_reference: datetime) -> tuple[datetime | None, datetime | None, str]:
    """Determine market session window and status using NYSE exchange calendar.

    Returns (market_open_at, market_close_at, status_for_display).
    Status can be: open, pre-market, after-hours, weekend, holiday, closed.
    """
    session_state = get_session_state(local_reference)
    local_date = local_reference.date()

    market_open = local_reference.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = local_reference.replace(hour=16, minute=0, second=0, microsecond=0)

    # For early-close days, market_close is at 13:00
    if session_state == "early_close":
        market_close = local_reference.replace(hour=13, minute=0, second=0, microsecond=0)

    # Determine next open time based on session state
    if session_state in {"holiday", "weekend"}:
        next_open_date = next_trading_day(local_date)
        next_open = datetime(
            next_open_date.year, next_open_date.month, next_open_date.day,
            9, 30, tzinfo=local_reference.tzinfo
        )
        return next_open, None, session_state

    if session_state in {"closed", "pre_market"}:
        return market_open, market_close, "pre-market"

    if session_state in {"after_hours", "closed"}:
        next_open_date = next_trading_day(local_date)
        next_open = datetime(
            next_open_date.year, next_open_date.month, next_open_date.day,
            9, 30, tzinfo=local_reference.tzinfo
        )
        return next_open, market_close, "after-hours"

    # regular_open or early_close
    return market_open, market_close, "open"


def _build_scan_summary(
    tickers: list[str],
    results: list[ScanResult],
    errors: list[ScanError],
    notes: list[str] | None = None,
) -> ScanSummary:
    failed_tickers = [item.ticker for item in errors]
    success_count = len(results)
    error_count = len(errors)
    partial_failure = error_count > 0
    if partial_failure:
        message = f"Scan completed with {success_count} successful tickers and {error_count} failures."
    else:
        message = f"Scan completed successfully for {success_count} tickers."
    summary_notes = list(notes or [])
    if partial_failure:
        summary_notes.append(
            "Partial failure: review the per-ticker error lines for market-data issues or ticker-specific problems."
        )

    return ScanSummary(
        requested_count=len(tickers),
        success_count=success_count,
        error_count=error_count,
        partial_failure=partial_failure,
        message=message,
        failed_tickers=failed_tickers,
        notes=summary_notes,
    )


def _build_operation_notes(
    *,
    market: dict,
    explanation: str,
    settings,
    used_ai_explanation: bool,
    market_session: dict | None,
    event_calendar: dict | None,
) -> list[str]:
    notes: list[str] = []
    data_quality = market.get("data_quality") or {}
    quality_summary = data_quality.get("summary")
    if quality_summary and quality_summary != "ok":
        notes.append(f"Data quality: {quality_summary}.")

    if market_session is not None:
        session_note = market_session.get("freshness_note")
        if session_note:
            notes.append(session_note)

    notes.extend(_event_calendar_notes(str(market.get("ticker") or "UNKNOWN"), event_calendar))
    notes.extend(_economic_events_notes(market.get("generated_at")))

    if used_ai_explanation:
        if not getattr(settings, "openai_api_key", None):
            notes.append("OpenAI explanation is disabled, so a rule-based explanation was used.")
        elif "Лимит OpenAI-вызовов исчерпан" in explanation:
            notes.append("OpenAI call budget was exhausted, so a rule-based explanation was used.")
        elif "Объяснение от LLM недоступно" in explanation:
            notes.append("OpenAI response was unavailable, so a rule-based explanation was used.")

    return notes


def _event_calendar_notes(ticker: str, event_calendar: Any) -> list[str]:
    if not event_calendar:
        return []

    events = getattr(event_calendar, "upcoming_events", None)
    if events is None and isinstance(event_calendar, dict):
        events = event_calendar.get("upcoming_events")
    if not events:
        return []

    notes: list[str] = []
    summary = getattr(event_calendar, "summary", None)
    if summary is None and isinstance(event_calendar, dict):
        summary = event_calendar.get("summary")
    if summary:
        notes.append(f"{ticker.upper()} event calendar: {summary}.")

    for event in events:
        name = getattr(event, "name", None)
        if name is None and isinstance(event, dict):
            name = event.get("name")
        scheduled_at = getattr(event, "scheduled_at", None)
        if scheduled_at is None and isinstance(event, dict):
            scheduled_at = event.get("scheduled_at")
        if name and scheduled_at is not None:
            notes.append(f"{ticker.upper()} {name} event around {scheduled_at.date().isoformat()}.")
    return notes


def _save_edgar_filings(db: Session, ticker: str) -> None:
    try:
        collection = fetch_recent_filings(ticker)
    except Exception:
        logger.exception(
            "edgar_filings_fetch_failed",
            extra={"component": "edgar", "ticker": ticker},
        )
        return

    if collection.error:
        logger.warning(
            "edgar_filings_error",
            extra={"component": "edgar", "ticker": ticker, "error": collection.error},
        )
        return

    if not collection.filings:
        logger.debug(
            "edgar_no_filings",
            extra={"component": "edgar", "ticker": ticker},
        )
        return

    try:
        snapshot_dict = collection.as_source_snapshot_dict()
        snapshot = upsert_source_snapshot(db, market=snapshot_dict)
    except Exception:
        logger.exception(
            "edgar_snapshot_persist_failed",
            extra={"component": "persistence", "ticker": ticker},
        )
        return

    logger.info(
        "edgar_filings_saved",
        extra={
            "component": "persistence",
            "ticker": snapshot.ticker,
            "provider_name": snapshot.provider_name,
            "source_tier": snapshot.source_tier,
            "filing_count": len(collection.filings),
        },
    )


def _economic_events_notes(generated_at: Any) -> list[str]:
    """Return notes about upcoming important economic events."""
    from datetime import datetime as dt

    if not isinstance(generated_at, dt):
        return []

    try:
        ref_date = generated_at.date()
    except Exception:
        return []

    notes: list[str] = []
    upcoming = upcoming_events(reference_date=ref_date, days_ahead=7)
    if not upcoming:
        return notes

    high_importance = [e for e in upcoming if e.importance == "high"]
    if high_importance:
        event_names = ", ".join([e.name for e in high_importance[:3]])
        notes.append(f"Upcoming high-impact economic events: {event_names}.")

    return notes


def _save_macro_indicators(db: Session) -> None:
    settings = get_settings()
    try:
        collection = fetch_macro_indicators(api_key=settings.fred_api_key)
    except Exception:
        logger.exception(
            "fred_indicators_fetch_failed",
            extra={"component": "fred"},
        )
        return

    if collection.error:
        logger.debug(
            "fred_indicators_error",
            extra={"component": "fred", "error": collection.error},
        )
        return

    if not collection.observations:
        logger.debug(
            "fred_no_observations",
            extra={"component": "fred"},
        )
        return

    try:
        snapshot_dict = collection.as_source_snapshot_dict()
        snapshot = upsert_source_snapshot(db, market=snapshot_dict)
    except Exception:
        logger.exception(
            "fred_snapshot_persist_failed",
            extra={"component": "persistence"},
        )
        return

    logger.info(
        "fred_indicators_saved",
        extra={
            "component": "persistence",
            "provider_name": snapshot.provider_name,
            "source_tier": snapshot.source_tier,
            "observation_count": len(collection.observations),
        },
    )
