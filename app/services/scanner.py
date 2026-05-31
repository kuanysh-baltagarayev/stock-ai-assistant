from datetime import datetime, timezone
import logging

from sqlalchemy.orm import Session

from app.models import AnalysisSnapshot
from app.schemas import (
    AnalyzeResponse,
    DataQualityFlags,
    FXNormalization,
    ScanError,
    ScanResponse,
    ScanResult,
    ScanSummary,
    SourceProvenance,
)
from app.services.ai_explainer import explain_analysis, rule_based_explanation
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
    fundamentals = extract_fundamentals(market["info"])
    technicals = calculate_indicators(market["history"])
    scoring = score_stock(market["price"], technicals, fundamentals)
    if db is not None:
        _save_instrument(db, market["ticker"], market["info"], market["currency"])
    settings = get_settings()

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
                recommendation=analysis.recommendation,
                short_reason=analysis.short_reason,
            )
        )

    results.sort(key=lambda item: item.final_score, reverse=True)
    summary = _build_scan_summary(tickers=tickers, results=results, errors=errors)

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


def _build_scan_summary(
    tickers: list[str],
    results: list[ScanResult],
    errors: list[ScanError],
) -> ScanSummary:
    failed_tickers = [item.ticker for item in errors]
    success_count = len(results)
    error_count = len(errors)
    partial_failure = error_count > 0
    if partial_failure:
        message = f"Scan completed with {success_count} successful tickers and {error_count} failures."
    else:
        message = f"Scan completed successfully for {success_count} tickers."
    notes = []
    if partial_failure:
        notes.append(
            "Partial failure: review the per-ticker error lines for market-data issues or ticker-specific problems."
        )

    return ScanSummary(
        requested_count=len(tickers),
        success_count=success_count,
        error_count=error_count,
        partial_failure=partial_failure,
        message=message,
        failed_tickers=failed_tickers,
        notes=notes,
    )


def _build_operation_notes(
    *,
    market: dict,
    explanation: str,
    settings,
    used_ai_explanation: bool,
) -> list[str]:
    notes: list[str] = []
    data_quality = market.get("data_quality") or {}
    quality_summary = data_quality.get("summary")
    if quality_summary and quality_summary != "ok":
        notes.append(f"Data quality: {quality_summary}.")

    if used_ai_explanation:
        if not getattr(settings, "openai_api_key", None):
            notes.append("OpenAI explanation is disabled, so a rule-based explanation was used.")
        elif "Лимит OpenAI-вызовов исчерпан" in explanation:
            notes.append("OpenAI call budget was exhausted, so a rule-based explanation was used.")
        elif "Объяснение от LLM недоступно" in explanation:
            notes.append("OpenAI response was unavailable, so a rule-based explanation was used.")

    return notes
