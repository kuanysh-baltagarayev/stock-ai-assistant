from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    SecFilingsContext,
    SourceProvenance,
)
from app.services.ai_explainer import explain_analysis, rule_based_explanation
from app.services.edgar_collector import EdgarCollection, fetch_recent_filings
from app.services.economic_calendar import upcoming_events
from app.services.exchange_calendar import get_session_state, next_trading_day
from app.services.fred_collector import FredCollection, fetch_macro_indicators
from app.services.macro_context import MacroContext, build_macro_context, macro_context_summary
from app.services.market_regime import (
    MarketRegime,
    collect_market_regime,
    market_regime_summary,
)
from app.services.news_collector import NewsContext, build_news_context, high_impact_news
from app.services.risk_overlay import calculate_risk_overlay, risk_overlay_notes
from app.services.sector_sensitivity import macro_impact_notes, get_sector_sensitivity
from app.services.instruments import upsert_instrument
from app.services.history import cleanup_old_snapshots
from app.services.indicators import calculate_indicators
from app.services.coverage import build_coverage_summary, format_coverage_gap_line
from app.config import get_settings
from app.services.market_data import (
    MarketDataError,
    extract_fundamentals,
    get_market_data,
)
from app.services.source_snapshots import upsert_source_snapshot
from app.services.scoring import score_stock


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FredMacroContext:
    collection: FredCollection | None = None
    latest: dict[str, float | None] = field(default_factory=dict)
    history: dict[str, list[float]] = field(default_factory=dict)
    notes: tuple[str, ...] = ()


def analyze_ticker(
    ticker: str,
    db: Session | None = None,
    use_ai_explanation: bool = True,
    include_edgar_context: bool = True,
    include_news: bool = True,
    fred_macro_context: FredMacroContext | None = None,
    market_regime: MarketRegime | None = None,
) -> AnalyzeResponse:
    logger.debug("analysis_started", extra={"component": "scanner", "ticker": ticker})
    market = get_market_data(ticker, db=db)
    edgar_collection = _fetch_edgar_filings(market["ticker"]) if include_edgar_context else None
    settings = get_settings()
    fred_macro = fred_macro_context or _collect_fred_macro(settings)
    regime = market_regime if market_regime is not None else _collect_market_regime(settings)
    if db is not None:
        _save_source_snapshot(db, market)
        if edgar_collection is not None:
            _save_edgar_filings(db, edgar_collection)
        _save_macro_indicators(db, fred_macro.collection)
    fundamentals = extract_fundamentals(market["info"])
    technicals = calculate_indicators(market["history"])

    # Build macro context for adaptive scoring; collect news first so political
    # risk from breaking headlines can feed into the catalyst risk layer.
    generated_at = datetime.now(timezone.utc)
    news_context = _collect_news_context(market["ticker"], settings, include_news)
    macro = build_macro_context(
        generated_at,
        fred_latest=fred_macro.latest,
        fred_history=fred_macro.history,
        news_context=news_context,
    )
    sec_filings_payload = _build_sec_filings_payload(edgar_collection)
    scoring = score_stock(
        market["price"],
        technicals,
        fundamentals,
        macro_context=macro,
        event_calendar=market.get("event_calendar"),
        sec_filings=sec_filings_payload,
        reference_time=generated_at,
        market_regime=regime,
    )

    if db is not None:
        _save_instrument(db, market["ticker"], market["info"], market["currency"])
    market_session = _build_market_session(market)
    news_payload, news_notes = _build_news_payload(news_context)

    payload = {
        "ticker": market["ticker"],
        "generated_at": generated_at,
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
        "sec_filings": sec_filings_payload,
        "news": news_payload,
    }

    if use_ai_explanation:
        explanation = explain_analysis(_json_ready(payload), scoring.reasons)
    else:
        explanation = rule_based_explanation(_json_ready(payload), scoring.reasons)

    operation_notes = _build_operation_notes(
        market=market,
        explanation=explanation,
        settings=settings,
        used_ai_explanation=use_ai_explanation,
        market_session=market_session,
        event_calendar=market.get("event_calendar"),
        sec_filings=payload.get("sec_filings"),
        risk_score=scoring.scores.risk_score,
        fundamentals=fundamentals,
        generated_at=payload.get("generated_at"),
        macro_context=macro,
        fred_notes=fred_macro.notes,
        market_regime=regime,
    )
    operation_notes.extend(news_notes)

    # Deterministic score decomposition for API / Telegram / CLI
    from app.services.score_decomposition import (
        decompose_scores,
        decomposition_as_payload,
    )

    decomp = decompose_scores(
        scoring.scores,
        scoring.reasons,
        data_quality=_build_data_quality(market),
        final_label=scoring.recommendation,
    )
    response = AnalyzeResponse(
        **payload,
        explanation=explanation,
        operation_notes=operation_notes,
        score_decomposition=decomposition_as_payload(decomp),
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


def _collect_news_context(
    symbol: str, settings: Any, include_news: bool
) -> NewsContext | None:
    """Fetch NewsContext for a ticker; returns None when disabled or on error."""
    if not include_news:
        return None
    try:
        return build_news_context(symbol, settings)
    except Exception:
        logger.warning(
            "news_context_failed",
            extra={"component": "news", "ticker": symbol},
            exc_info=True,
        )
        return None


def _build_news_payload(
    context: NewsContext | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Build the news payload dict and operation notes from a NewsContext."""
    if context is None or not context.items:
        return None, []

    payload = {
        "summary": context.summary,
        "overall_sentiment_score": context.overall_sentiment_score,
        "overall_sentiment_label": context.overall_sentiment_label,
        "articles": [
            {
                "title": item.title,
                "url": item.url,
                "source": item.source,
                "published_at": item.published_at,
                "summary": item.summary,
                "sentiment_score": item.sentiment_score,
                "sentiment_label": item.sentiment_label,
                "relevance": item.relevance,
                "category": item.category,
            }
            for item in context.items
        ],
    }

    notes: list[str] = []
    if context.summary:
        notes.append(f"News: {context.summary}")
    for item in high_impact_news(context)[:2]:
        direction = "negative" if (item.sentiment_score or 0) < 0 else "positive"
        notes.append(f"High-impact news ({direction}, {item.source}): {item.title}")
    return payload, notes


def _build_news(
    symbol: str, settings: Any, include_news: bool
) -> tuple[dict[str, Any] | None, list[str]]:
    """Legacy wrapper kept for callers outside analyze_ticker."""
    ctx = _collect_news_context(symbol, settings, include_news)
    return _build_news_payload(ctx)


def scan_tickers(tickers: list[str], db: Session | None = None) -> ScanResponse:
    results: list[ScanResult] = []
    errors: list[ScanError] = []
    notes: list[str] = []
    settings = get_settings()
    fred_macro = _collect_fred_macro(settings)
    notes.extend(fred_macro.notes)
    regime = _collect_market_regime(settings)
    notes.extend(market_regime_summary(regime))

    logger.info(
        "scan_started",
        extra={"component": "scanner", "ticker_count": len(tickers), "persisting": db is not None},
    )

    for ticker in tickers:
        try:
            analysis = analyze_ticker(
                ticker,
                db=db,
                use_ai_explanation=False,
                include_edgar_context=False,
                include_news=False,
                fred_macro_context=fred_macro,
                market_regime=regime,
            )
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
                source_provider=getattr(getattr(analysis, "source_provenance", None), "provider_name", None),
                source_tier=getattr(getattr(analysis, "source_provenance", None), "source_tier", None),
                market_session_status=getattr(getattr(analysis, "market_session", None), "status", None),
                freshness_state=getattr(getattr(analysis, "market_session", None), "freshness_state", None),
                data_quality_summary=getattr(getattr(analysis, "data_quality", None), "summary", None),
                stale=bool(getattr(getattr(analysis, "data_quality", None), "stale", False)),
                delayed=bool(getattr(getattr(analysis, "data_quality", None), "delayed", False)),
                missing=bool(getattr(getattr(analysis, "data_quality", None), "missing", False)),
                source_disagreed=bool(getattr(getattr(analysis, "data_quality", None), "source_disagreed", False)),
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
        split_detected=bool(data_quality.get("split_detected", False)),
        dividend_detected=bool(data_quality.get("dividend_detected", False)),
        missing_candles=int(data_quality.get("missing_candles", 0)),
        partial_session=bool(data_quality.get("partial_session", False)),
        adjustment_policy_warning=data_quality.get("adjustment_policy_warning"),
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
    sec_filings: dict | None,
    risk_score: float,
    fundamentals: Any,
    generated_at: Any = None,
    macro_context: MacroContext | None = None,
    fred_notes: tuple[str, ...] = (),
    market_regime: MarketRegime | None = None,
) -> list[str]:
    notes: list[str] = []
    data_quality = market.get("data_quality") or {}
    quality_summary = data_quality.get("summary")
    if quality_summary and quality_summary != "ok":
        notes.append(f"Data quality: {quality_summary}.")

    # Per-analysis source coverage summary
    sec_available = bool(sec_filings)
    cik_available = bool(sec_filings and isinstance(sec_filings, dict) and sec_filings.get("cik"))
    # News availability: we check via the same news context used by the
    # caller — here we skip it because news is not passed as a parameter
    # to this function. The coverage summary still detects sec, macro and
    # regime gaps correctly.
    macro_present = macro_context is not None and bool(
        getattr(macro_context, "rate_direction", None)
        or getattr(macro_context, "inflation_level", None)
        or getattr(macro_context, "latest_fed_funds_rate", None)
    )
    regime_present = market_regime is not None and getattr(market_regime, "confidence", 0) > 0
    coverage_summary = build_coverage_summary(
        has_sec_filings=sec_available,
        cik_available=cik_available,
        has_news=False,  # best-effort; news_notes are appended separately
        has_macro_context=macro_present,
        has_market_regime=regime_present,
        provider_name=market.get("provider_name"),
        source_tier=market.get("source_tier"),
        stale=bool(data_quality.get("stale")),
        delayed=bool(data_quality.get("delayed")),
        missing=bool(data_quality.get("missing")),
        source_disagreed=bool(data_quality.get("source_disagreed")),
        confidence=data_quality.get("confidence"),
    )
    coverage_line = format_coverage_gap_line(coverage_summary)
    if coverage_line:
        notes.append(coverage_line)

    notes.extend(fred_notes)
    notes.extend(market_regime_summary(market_regime))

    if market_session is not None:
        session_note = market_session.get("freshness_note")
        if session_note:
            notes.append(session_note)

    notes.extend(_event_calendar_notes(str(market.get("ticker") or "UNKNOWN"), event_calendar))
    notes.extend(_sec_filing_notes(str(market.get("ticker") or "UNKNOWN"), sec_filings))
    notes.extend(_economic_events_notes(generated_at))
    notes.extend(_macro_context_notes(generated_at, macro_context))
    notes.extend(_sector_catalyst_notes(market.get("info", {}).get("sector"), event_calendar, generated_at, macro_context))
    notes.extend(_sector_sensitivity_notes(market.get("info", {}).get("sector"), generated_at, macro_context))
    notes.extend(
        _risk_overlay_notes(
            risk_score,
            market.get("info", {}).get("sector"),
            fundamentals,
            generated_at,
            macro_context,
        )
    )

    if used_ai_explanation:
        api_key = getattr(settings, "deepseek_api_key", None) or getattr(settings, "openai_api_key", None)
        if not api_key:
            notes.append("LLM explanation is disabled (neither OPENAI_API_KEY nor DEEPSEEK_API_KEY set), so a rule-based explanation was used.")
        elif "Лимит LLM-вызовов исчерпан" in explanation:
            notes.append("LLM call budget was exhausted, so a rule-based explanation was used.")
        elif "Объяснение от LLM недоступно" in explanation:
            notes.append("LLM response was unavailable, so a rule-based explanation was used.")

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


def _fetch_edgar_filings(ticker: str) -> EdgarCollection | None:
    try:
        collection = fetch_recent_filings(ticker)
    except Exception:
        logger.exception(
            "edgar_filings_fetch_failed",
            extra={"component": "edgar", "ticker": ticker},
        )
        return None
    if collection.error:
        logger.warning(
            "edgar_filings_error",
            extra={"component": "edgar", "ticker": ticker, "error": collection.error},
        )
        return None
    if not collection.filings:
        logger.debug(
            "edgar_no_filings",
            extra={"component": "edgar", "ticker": ticker},
        )
        return None
    return collection


def _save_edgar_filings(db: Session, collection: EdgarCollection) -> None:
    ticker = collection.ticker

    if not collection.filings:
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


def _build_sec_filings_payload(collection: EdgarCollection | None) -> dict[str, Any] | None:
    if collection is None or not collection.filings:
        return None

    summary_forms = ", ".join(
        f"{filing.form_type} ({filing.filing_date})" for filing in collection.filings[:3]
    )
    return SecFilingsContext(
        summary=f"Recent SEC filings: {summary_forms}.",
        cik=collection.cik,
        company_name=collection.company_name,
        fetched_at=collection.fetched_at,
        recent_filings=[
            {
                "form_type": filing.form_type,
                "filing_date": filing.filing_date,
                "accession_number": filing.accession_number,
                "description": filing.description,
                "sec_url": filing.sec_url,
            }
            for filing in collection.filings[:5]
        ],
    ).model_dump(mode="json")


def _sec_filing_notes(ticker: str, sec_filings: Any) -> list[str]:
    if not sec_filings:
        return []

    filings = getattr(sec_filings, "recent_filings", None)
    if filings is None and isinstance(sec_filings, dict):
        filings = sec_filings.get("recent_filings")
    if not filings:
        return []

    notes: list[str] = []
    summary = getattr(sec_filings, "summary", None)
    if summary is None and isinstance(sec_filings, dict):
        summary = sec_filings.get("summary")
    if summary:
        notes.append(f"{ticker.upper()} {summary}")

    filing = filings[0]
    if isinstance(filing, dict):
        form_type = filing.get("form_type")
        filing_date = filing.get("filing_date")
        description = filing.get("description")
    else:
        form_type = getattr(filing, "form_type", None)
        filing_date = getattr(filing, "filing_date", None)
        description = getattr(filing, "description", None)
    if form_type and filing_date:
        detail = f"{ticker.upper()} latest SEC filing: {form_type} on {filing_date}"
        if description:
            detail = f"{detail} ({description})"
        notes.append(detail + ".")
    return notes


def _macro_context_notes(generated_at: Any, macro_context: MacroContext | None = None) -> list[str]:
    """Return notes about macroeconomic context for alert interpretation."""
    if not isinstance(generated_at, datetime):
        return []

    try:
        macro = macro_context or build_macro_context(generated_at)
        return macro_context_summary(macro)
    except Exception:
        logger.debug(
            "macro_context_notes_failed",
            extra={"component": "macro_context"},
            exc_info=True,
        )
        return []


def _sector_sensitivity_notes(
    sector: str | None,
    generated_at: Any,
    macro_context: MacroContext | None = None,
) -> list[str]:
    """Return notes about how macro conditions affect this sector."""
    if not sector or not isinstance(generated_at, datetime):
        return []

    try:
        macro = macro_context or build_macro_context(generated_at)
        notes = macro_impact_notes(
            sector,
            fed_rate_direction=macro.rate_direction,
            inflation_level=macro.inflation_level,
            growth_outlook=None,  # Not directly available from macro context
        )
        return notes
    except Exception:
        logger.debug(
            "sector_sensitivity_notes_failed",
            extra={"component": "sector_sensitivity", "sector": sector},
            exc_info=True,
        )
        return []


def _sector_catalyst_notes(
    sector: str | None,
    event_calendar: Any,
    generated_at: Any,
    macro_context: MacroContext | None = None,
) -> list[str]:
    """Explain when sector sensitivity is materially shaping catalyst risk."""
    if not sector or not isinstance(generated_at, datetime):
        return []

    sensitivity = get_sector_sensitivity(sector)
    if sensitivity is None:
        return []

    notes: list[str] = []

    try:
        macro = macro_context or build_macro_context(generated_at)
        if macro.upcoming_high_impact_events:
            if macro.rate_direction == "rising" and sensitivity.fed_rate_sensitivity <= -0.5:
                notes.append(
                    f"Sector-adjusted event risk: {sector} may react more sharply to upcoming macro events because rising rates tend to pressure this sector."
                )
            elif macro.rate_direction == "rising" and sensitivity.fed_rate_sensitivity >= 0.4:
                notes.append(
                    f"Sector-adjusted event risk: {sector} is relatively more resilient to rising-rate macro events than most sectors."
                )
            elif macro.inflation_level == "elevated" and sensitivity.inflation_sensitivity <= -0.2:
                notes.append(
                    f"Sector-adjusted event risk: elevated inflation can amplify near-term catalyst risk for {sector}."
                )

        nearest_earnings_days = _nearest_earnings_days(event_calendar, generated_at)
        if nearest_earnings_days is not None and nearest_earnings_days <= 14:
            if sensitivity.growth_sensitivity >= 0.65:
                notes.append(
                    f"Sector-adjusted event risk: upcoming earnings may move {sector} names more sharply than defensive sectors."
                )
            elif sensitivity.growth_sensitivity <= 0.25:
                notes.append(
                    f"Sector-adjusted event risk: upcoming earnings are usually less disruptive for {sector} than for high-growth sectors."
                )
    except Exception:
        logger.debug(
            "sector_catalyst_notes_failed",
            extra={"component": "sector_sensitivity", "sector": sector},
            exc_info=True,
        )
        return []

    return notes


def _risk_overlay_notes(
    risk_score: float,
    sector: str | None,
    fundamentals: Any,
    generated_at: Any,
    macro_context: MacroContext | None = None,
) -> list[str]:
    """Return notes about risk overlay based on macro conditions."""
    if not isinstance(generated_at, datetime):
        return []

    try:
        macro = macro_context or build_macro_context(generated_at)
        sector_sensitivity = get_sector_sensitivity(sector) if sector else None
        dividend_yield = None
        if isinstance(fundamentals, dict):
            dividend_yield = fundamentals.get("dividend_yield")
        elif hasattr(fundamentals, "dividend_yield"):
            dividend_yield = fundamentals.dividend_yield

        overlay = calculate_risk_overlay(
            risk_score,
            macro_context=macro,
            sector_sensitivity=sector_sensitivity,
            dividend_yield=dividend_yield,
        )
        return risk_overlay_notes(overlay)
    except Exception:
        logger.debug(
            "risk_overlay_notes_failed",
            extra={"component": "risk_overlay"},
            exc_info=True,
        )
        return []


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


def _nearest_earnings_days(event_calendar: Any, now: datetime) -> int | None:
    events = getattr(event_calendar, "upcoming_events", None)
    if events is None and isinstance(event_calendar, dict):
        events = event_calendar.get("upcoming_events")
    if not events:
        return None

    nearest: int | None = None
    for event in events:
        if isinstance(event, dict):
            name = str(event.get("name") or "").lower()
            scheduled_at = event.get("scheduled_at") or event.get("window_start_at")
        else:
            name = str(getattr(event, "name", "")).lower()
            scheduled_at = getattr(event, "scheduled_at", None) or getattr(event, "window_start_at", None)
        if name != "earnings":
            continue
        scheduled_dt = _parse_datetime_like(scheduled_at)
        if scheduled_dt is None:
            continue
        days_until = (scheduled_dt.date() - now.date()).days
        if days_until < 0:
            continue
        if nearest is None or days_until < nearest:
            nearest = days_until
    return nearest


def _parse_datetime_like(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _collect_market_regime(settings: Any) -> MarketRegime:
    """Collect the broad-market regime once, gated by settings.

    Disabled by default; when ``market_regime_enabled`` is set the collector
    fetches index/VIX/yield/sector proxies via yfinance. Any failure degrades
    confidence rather than breaking analysis.
    """
    try:
        return collect_market_regime(
            enabled=bool(getattr(settings, "market_regime_enabled", False)),
            timeout=float(getattr(settings, "market_data_timeout_seconds", 20.0)),
        )
    except Exception:
        logger.exception(
            "market_regime_collection_failed",
            extra={"component": "market_regime"},
        )
        return collect_market_regime(enabled=False)


def _collect_fred_macro(settings: Any) -> FredMacroContext:
    try:
        collection = fetch_macro_indicators(api_key=getattr(settings, "fred_api_key", None))
    except Exception:
        logger.exception(
            "fred_indicators_fetch_failed",
            extra={"component": "fred"},
        )
        return FredMacroContext(notes=("FRED macro data unavailable: collector failed.",))

    latest = collection.latest_by_series()
    history = collection.history_by_series()
    notes: list[str] = []
    if collection.error:
        if latest:
            notes.append(f"FRED macro data partially unavailable: {collection.error}.")
        else:
            notes.append(f"FRED macro data unavailable: {collection.error}.")
    elif not latest:
        notes.append("FRED macro data unavailable: no observations returned.")
    notes.extend(_fred_staleness_notes(collection))

    return FredMacroContext(
        collection=collection,
        latest=latest,
        history=history,
        notes=tuple(notes),
    )


def _fred_staleness_notes(collection: FredCollection) -> list[str]:
    if not collection.observations:
        return []

    fetched_at = collection.fetched_at
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)

    stale_series: list[str] = []
    for observation in collection.observations:
        observed_date = _parse_fred_observation_date(observation.date)
        if observed_date is None:
            continue
        age_days = (fetched_at.date() - observed_date.date()).days
        if age_days > 120:
            stale_series.append(f"{observation.series_id} {observation.date}")

    if not stale_series:
        return []

    sample = ", ".join(stale_series[:3])
    return [f"FRED macro data may be stale: latest old observations include {sample}."]


def _parse_fred_observation_date(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _save_macro_indicators(db: Session, collection: FredCollection | None) -> None:
    if collection is None:
        return

    try:
        if collection.error and not collection.observations:
            logger.debug(
                "fred_indicators_error",
                extra={"component": "fred", "error": collection.error},
            )
            return
    except Exception:
        logger.debug(
            "fred_indicators_collection_invalid",
            extra={"component": "fred"},
            exc_info=True,
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
