from datetime import datetime, timezone
import logging

from sqlalchemy.orm import Session

from app.models import AnalysisSnapshot
from app.schemas import AnalyzeResponse, ScanError, ScanResponse, ScanResult, ScanSummary
from app.services.ai_explainer import explain_analysis, rule_based_explanation
from app.services.history import cleanup_old_snapshots
from app.services.indicators import calculate_indicators
from app.config import get_settings
from app.services.market_data import MarketDataError, extract_fundamentals, get_market_data
from app.services.scoring import score_stock


logger = logging.getLogger(__name__)


def analyze_ticker(
    ticker: str,
    db: Session | None = None,
    use_ai_explanation: bool = True,
) -> AnalyzeResponse:
    logger.debug("analysis_started", extra={"component": "scanner", "ticker": ticker})
    market = get_market_data(ticker)
    fundamentals = extract_fundamentals(market["info"])
    technicals = calculate_indicators(market["history"])
    scoring = score_stock(market["price"], technicals, fundamentals)

    payload = {
        "ticker": market["ticker"],
        "generated_at": datetime.now(timezone.utc),
        "price": market["price"],
        "currency": market["currency"],
        "fundamentals": fundamentals.model_dump(),
        "technicals": technicals.model_dump(),
        "scores": scoring.scores.model_dump(),
        "recommendation": scoring.recommendation,
        "short_reason": scoring.short_reason,
    }

    if use_ai_explanation:
        explanation = explain_analysis(_json_ready(payload), scoring.reasons)
    else:
        explanation = rule_based_explanation(_json_ready(payload), scoring.reasons)

    response = AnalyzeResponse(**payload, explanation=explanation)
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


def _json_ready(payload: dict) -> dict:
    converted = payload.copy()
    generated_at = converted.get("generated_at")
    if isinstance(generated_at, datetime):
        converted["generated_at"] = generated_at.isoformat()
    return converted


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

    return ScanSummary(
        requested_count=len(tickers),
        success_count=success_count,
        error_count=error_count,
        partial_failure=partial_failure,
        message=message,
        failed_tickers=failed_tickers,
    )
