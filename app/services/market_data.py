import logging
import time
from collections.abc import Callable
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
        price = _first_number(
            _fast_info_value(fast_info, "last_price"),
            info.get("currentPrice"),
            info.get("regularMarketPrice"),
            history["Close"].iloc[-1],
        )
        if price is None:
            raise MarketDataError(f"Could not determine current price for {symbol}.")

        currency = (
            _fast_info_value(fast_info, "currency")
            or info.get("currency")
            or info.get("financialCurrency")
        )

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
