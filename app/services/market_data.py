from typing import Any

import pandas as pd
import yfinance as yf

from app.schemas import Fundamentals


class MarketDataError(RuntimeError):
    pass


def normalize_ticker(ticker: str) -> str:
    symbol = ticker.strip().upper()
    if not symbol:
        raise MarketDataError("Ticker must not be empty.")
    return symbol


def get_market_data(ticker: str) -> dict[str, Any]:
    symbol = normalize_ticker(ticker)
    stock = yf.Ticker(symbol)

    try:
        history = stock.history(period="1y", interval="1d", auto_adjust=False)
    except Exception as exc:
        raise MarketDataError(f"Could not download market history for {symbol}: {exc}") from exc

    if history is None or history.empty or "Close" not in history.columns:
        raise MarketDataError(f"No historical price data returned for {symbol}.")

    history = history.dropna(subset=["Close"]).copy()
    if history.empty:
        raise MarketDataError(f"Historical price data for {symbol} has no valid close prices.")

    info = _safe_info(stock)
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

    return {
        "ticker": symbol,
        "price": price,
        "currency": currency,
        "history": history,
        "info": info,
    }


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


def _safe_info(stock: yf.Ticker) -> dict[str, Any]:
    try:
        info = stock.info
    except Exception:
        return {}
    return info if isinstance(info, dict) else {}


def _safe_fast_info(stock: yf.Ticker) -> Any:
    try:
        return stock.fast_info
    except Exception:
        return {}


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
