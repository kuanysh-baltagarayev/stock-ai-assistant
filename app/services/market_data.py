import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar

import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session

from app.config import get_settings
from app.schemas import Fundamentals
from app.services.providers import (
    DEFAULT_PROVIDER_NAME,
    provider_registry_payload,
    record_provider_failure,
    record_provider_success,
)


logger = logging.getLogger(__name__)

T = TypeVar("T")


class MarketDataError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 503) -> None:
        super().__init__(message)
        self.status_code = status_code


class InvalidTickerError(MarketDataError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=400)


def normalize_ticker(ticker: str) -> str:
    symbol = ticker.strip().upper()
    if not symbol:
        raise InvalidTickerError("Ticker must not be empty.")
    return symbol


def get_market_data(ticker: str, db: Session | None = None) -> dict[str, Any]:
    symbol = normalize_ticker(ticker)
    settings = get_settings()
    provider_profile = provider_registry_payload(DEFAULT_PROVIDER_NAME)
    fetched_at = datetime.now(timezone.utc)

    try:
        history = _with_retries(
            f"download market history for {symbol}",
            symbol,
            lambda: _download_history(symbol, settings.market_data_timeout_seconds),
            settings.market_data_max_attempts,
            settings.market_data_retry_backoff_seconds,
        )

        if history is None or history.empty or "Close" not in history.columns:
            raise MarketDataError(
                f"No historical price data returned for {symbol}.", status_code=404
            )

        history = history.dropna(subset=["Close"]).copy()
        if history.empty:
            raise MarketDataError(
                f"Historical price data for {symbol} has no valid close prices.",
                status_code=404,
            )

        stock = yf.Ticker(symbol)

        info = _safe_info(
            stock,
            symbol=symbol,
            attempts=settings.market_data_max_attempts,
            retry_backoff_seconds=settings.market_data_retry_backoff_seconds,
        )
        fast_info = _safe_fast_info(stock)
        fast_price = _to_float(_fast_info_value(fast_info, "last_price"))
        current_price = _to_float(info.get("currentPrice"))
        regular_market_price = _to_float(info.get("regularMarketPrice"))
        close_price = _to_float(history["Close"].iloc[-1])
        price, price_source = _first_number_with_source(
            (fast_price, "fast_info.last_price"),
            (current_price, "info.currentPrice"),
            (regular_market_price, "info.regularMarketPrice"),
            (close_price, "history.close"),
        )
        if price is None:
            raise MarketDataError(f"Could not determine current price for {symbol}.")

        currency = (
            _fast_info_value(fast_info, "currency")
            or info.get("currency")
            or info.get("financialCurrency")
        )
        latest_history_timestamp = _latest_history_timestamp(history)
        data_quality = _build_data_quality(
            info=info,
            price=price,
            price_source=price_source,
            close_price=close_price,
            fast_price=fast_price,
            current_price=current_price,
            regular_market_price=regular_market_price,
            latest_history_timestamp=latest_history_timestamp,
            fetched_at=fetched_at,
            currency=currency,
        )
        fx = _build_fx_metadata(currency=currency, fetched_at=fetched_at)
        source_provenance = {
            "provider_name": DEFAULT_PROVIDER_NAME,
            "source_url": provider_profile["source_url"],
            "source_tier": provider_profile["source_tier"],
            "data_category": provider_profile["data_category"],
            "extraction_method": "yfinance",
            "parser_version": f"yfinance-{getattr(yf, '__version__', 'unknown')}",
            "observed_at": fetched_at,
            "published_at": latest_history_timestamp,
            "fetched_at": fetched_at,
            "confidence": data_quality["confidence"],
            "content_hash": None,
        }

        if db is not None:
            try:
                record_provider_success(db=db, name=DEFAULT_PROVIDER_NAME, **provider_profile)
            except Exception:
                logger.exception(
                    "provider_registry_success_record_failed",
                    extra={"component": "persistence", "provider": DEFAULT_PROVIDER_NAME},
                )

        return {
            "ticker": symbol,
            "price": price,
            "currency": currency,
            "history": history,
            "info": info,
            "provider_name": DEFAULT_PROVIDER_NAME,
            "source_url": provider_profile["source_url"],
            "source_tier": provider_profile["source_tier"],
            "data_category": provider_profile["data_category"],
            "extraction_method": "yfinance",
            "parser_version": f"yfinance-{getattr(yf, '__version__', 'unknown')}",
            "observed_at": fetched_at,
            "published_at": latest_history_timestamp,
            "fetched_at": fetched_at,
            "price_source": price_source,
            "price_adjustment_policy": "raw_close",
            "corporate_actions_policy": "raw_close_no_auto_adjustment",
            "data_quality": data_quality,
            "fx": fx,
            "source_provenance": source_provenance,
        }
    except MarketDataError:
        if db is not None:
            try:
                record_provider_failure(
                    db=db,
                    name=DEFAULT_PROVIDER_NAME,
                    failure_mode="unavailable",
                    **provider_profile,
                )
            except Exception:
                logger.exception(
                    "provider_registry_failure_record_failed",
                    extra={"component": "persistence", "provider": DEFAULT_PROVIDER_NAME},
                )
        raise


def _download_history(symbol: str, timeout_seconds: float) -> pd.DataFrame:
    history = yf.download(
        symbol,
        period="1y",
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
        timeout=max(1, int(timeout_seconds)),
    )
    if isinstance(history, pd.DataFrame) and isinstance(history.columns, pd.MultiIndex):
        if symbol in history.columns.get_level_values(0):
            history = history[symbol]
        elif "Close" in history.columns.get_level_values(-1):
            history = history.xs("Close", axis=1, level=-1, drop_level=True)
    return history if isinstance(history, pd.DataFrame) else pd.DataFrame()


def extract_fundamentals(info: dict[str, Any]) -> Fundamentals:
    return Fundamentals(
        company_name=info.get("longName") or info.get("shortName"),
        sector=info.get("sector"),
        market_cap=_to_float(info.get("marketCap")),
        trailing_pe=_to_float(info.get("trailingPE")),
        forward_pe=_to_float(info.get("forwardPE")),
        revenue_growth=_to_float(info.get("revenueGrowth")),
        profit_margins=_to_float(info.get("profitMargins")),
        debt_to_equity=_to_float(info.get("debtToEquity")),
    )


def _safe_info(
    stock: yf.Ticker,
    *,
    symbol: str,
    attempts: int,
    retry_backoff_seconds: float,
) -> dict[str, Any]:
    try:
        info = _with_retries(
            f"load company profile for {symbol}",
            symbol,
            lambda: stock.info,
            attempts,
            retry_backoff_seconds,
        )
    except MarketDataError as exc:
        logger.warning("Using empty company profile for %s: %s", symbol, exc)
        return {}
    return info if isinstance(info, dict) else {}


def _safe_fast_info(stock: yf.Ticker) -> Any:
    try:
        return stock.fast_info
    except Exception:
        return {}


def _with_retries(
    action: str,
    symbol: str,
    operation: Callable[[], T],
    attempts: int,
    retry_backoff_seconds: float,
) -> T:
    total_attempts = max(1, attempts)
    delay = max(0.0, retry_backoff_seconds)
    last_exc: Exception | None = None

    for attempt in range(1, total_attempts + 1):
        try:
            return operation()
        except Exception as exc:  # pragma: no cover - retry path is covered via tests
            last_exc = exc
            if attempt >= total_attempts:
                break
            sleep_for = delay * attempt
            logger.warning(
                "Market data attempt %s/%s failed for %s while trying to %s: %s",
                attempt,
                total_attempts,
                symbol,
                action,
                exc,
            )
            if sleep_for:
                time.sleep(sleep_for)

    raise MarketDataError(
        f"Could not {action} after {total_attempts} attempts for {symbol}: {last_exc}"
    ) from last_exc


def _fast_info_value(fast_info: Any, key: str) -> Any:
    if fast_info is None:
        return None
    try:
        return fast_info.get(key)
    except Exception:
        return getattr(fast_info, key, None)


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _to_float(value)
        if number is not None:
            return number
    return None


def _first_number_with_source(*values: tuple[Any, str]) -> tuple[float | None, str | None]:
    for value, source in values:
        number = _to_float(value)
        if number is not None:
            return number, source
    return None, None


def _latest_history_timestamp(history: pd.DataFrame) -> datetime | None:
    if history.empty:
        return None

    index = history.index
    if len(index) == 0:
        return None

    value = index[-1]
    if isinstance(value, pd.Timestamp):
        dt_value = value.to_pydatetime()
    elif isinstance(value, datetime):
        dt_value = value
    else:
        return None

    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=timezone.utc)
    return dt_value.astimezone(timezone.utc)


def _build_data_quality(
    *,
    info: dict[str, Any],
    price: float,
    price_source: str | None,
    close_price: float | None,
    fast_price: float | None,
    current_price: float | None,
    regular_market_price: float | None,
    latest_history_timestamp: datetime | None,
    fetched_at: datetime,
    currency: str | None,
) -> dict[str, Any]:
    stale = False
    delayed = False
    estimated = False
    missing = not bool(info)
    source_disagreed = False

    if latest_history_timestamp is not None:
        stale = fetched_at - latest_history_timestamp > timedelta(days=1)
        delayed = latest_history_timestamp.date() < fetched_at.date()

    if price_source == "history.close":
        estimated = True
        delayed = True

    numeric_sources = [value for value in [fast_price, current_price, regular_market_price, close_price] if value is not None]
    if len(numeric_sources) >= 2:
        spread = max(numeric_sources) - min(numeric_sources)
        baseline = max(abs(price), 1.0)
        source_disagreed = spread / baseline > 0.01

    confidence = 1.0
    if stale:
        confidence -= 0.2
    if delayed:
        confidence -= 0.1
    if estimated:
        confidence -= 0.15
    if missing:
        confidence -= 0.1
    if source_disagreed:
        confidence -= 0.2
    if currency and currency.upper() != "USD":
        confidence -= 0.05
    confidence = max(0.0, round(confidence, 2))

    flags = [name for name, enabled in {
        "stale": stale,
        "delayed": delayed,
        "estimated": estimated,
        "missing": missing,
        "source_disagreed": source_disagreed,
    }.items() if enabled]
    summary = "ok" if not flags else ", ".join(flags)
    return {
        "stale": stale,
        "delayed": delayed,
        "estimated": estimated,
        "missing": missing,
        "source_disagreed": source_disagreed,
        "confidence": confidence,
        "summary": summary,
    }


def _build_fx_metadata(*, currency: str | None, fetched_at: datetime) -> dict[str, Any] | None:
    if currency is None:
        return None

    normalized_currency = currency.strip().upper()
    if not normalized_currency:
        return None

    note = None
    if normalized_currency != "USD":
        note = (
            "FX conversion not applied yet; values remain in the reported trading currency."
        )

    return {
        "base_currency": normalized_currency,
        "quote_currency": "USD",
        "fx_rate_to_usd": None,
        "fx_source": None,
        "fx_timestamp": None,
        "fx_assumption_note": note,
    }


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return number
