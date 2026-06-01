import json
import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from io import StringIO
from threading import Lock
from typing import Any, TypeVar
from urllib import error as urlerror
from urllib import parse
from urllib import request as urlrequest

import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session

from app.config import get_settings
from app.schemas import Fundamentals
from app.services.provider_collectors import (
    MarketDataCollection,
    ProviderContract,
)
from app.services.providers import (
    DEFAULT_PROVIDER_NAME,
    record_provider_failure,
    record_provider_success,
)
from app.services.runtime_budget import RuntimeBudgetExceeded, consume_runtime_budget


logger = logging.getLogger(__name__)

T = TypeVar("T")
_MARKET_DATA_CACHE_LOCK = Lock()
_MARKET_DATA_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


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
    provider_profile = ProviderContract.from_name(DEFAULT_PROVIDER_NAME)
    provider_payload = provider_profile.to_payload()
    cache_ttl_seconds = _market_data_cache_ttl_seconds(settings, provider_payload)
    cached_market = _get_cached_market_data(symbol, cache_ttl_seconds)
    if cached_market is not None:
        logger.debug(
            "market_data_cache_hit",
            extra={"component": "market_data", "ticker": symbol},
        )
        return cached_market

    fetched_at = datetime.now(timezone.utc)
    provider_call_budget = getattr(settings, "provider_call_budget", None)

    try:
        history, history_provider = _acquire_history(symbol, settings, provider_call_budget)
        history_profile = ProviderContract.from_name(history_provider)
        history_payload = history_profile.to_payload()
        if history_provider == DEFAULT_PROVIDER_NAME:
            extraction_method = "yfinance"
            parser_version = f"yfinance-{getattr(yf, '__version__', 'unknown')}"
        else:
            extraction_method = history_provider
            parser_version = f"{history_provider}-csv-v1"

        stock = yf.Ticker(symbol)

        info = _safe_info(
            stock,
            symbol=symbol,
            attempts=settings.market_data_max_attempts,
            retry_backoff_seconds=settings.market_data_retry_backoff_seconds,
            provider_call_budget=provider_call_budget,
        )
        fast_info = _safe_fast_info(
            stock,
            symbol=symbol,
            provider_call_budget=provider_call_budget,
        )
        finnhub_price = _finnhub_quote(
            symbol,
            settings.market_data_timeout_seconds,
            getattr(settings, "finnhub_api_key", None),
        )
        fast_price = _to_float(_fast_info_value(fast_info, "last_price"))
        current_price = _to_float(info.get("currentPrice"))
        regular_market_price = _to_float(info.get("regularMarketPrice"))
        close_price = _to_float(history["Close"].iloc[-1])
        price, price_source = _first_number_with_source(
            (finnhub_price, "finnhub.quote"),
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
        event_calendar = _build_event_calendar(info=info, fetched_at=fetched_at)
        source_provenance = {
            "provider_name": history_provider,
            "source_url": history_payload["source_url"],
            "source_tier": history_payload["source_tier"],
            "data_category": history_payload["data_category"],
            "extraction_method": extraction_method,
            "parser_version": parser_version,
            "observed_at": fetched_at,
            "published_at": latest_history_timestamp,
            "fetched_at": fetched_at,
            "confidence": data_quality["confidence"],
            "content_hash": None,
        }

        if db is not None:
            try:
                record_provider_success(db=db, name=history_provider, **history_payload)
            except Exception:
                logger.exception(
                    "provider_registry_success_record_failed",
                    extra={"component": "persistence", "provider": history_provider},
                )

        collection = MarketDataCollection(
            provider=history_profile,
            ticker=symbol,
            price=price,
            currency=currency,
            history=history,
            info=info,
            price_source=price_source,
            price_adjustment_policy="raw_close",
            corporate_actions_policy="raw_close_no_auto_adjustment",
            observed_at=fetched_at,
            published_at=latest_history_timestamp,
            fetched_at=fetched_at,
            data_quality=data_quality,
            fx=fx,
            event_calendar=event_calendar,
            source_provenance=source_provenance,
            provider_name=history_provider,
            source_url=history_profile.source_url,
            source_tier=history_profile.source_tier,
            data_category=history_profile.data_category,
            extraction_method=extraction_method,
            parser_version=parser_version,
            cache_hit=False,
        )
        market = collection.to_market_dict()
        _set_cached_market_data(symbol, market, cache_ttl_seconds)
        return _copy_market_data(market)
    except MarketDataError:
        if db is not None:
            try:
                record_provider_failure(
                    db=db,
                    name=DEFAULT_PROVIDER_NAME,
                    failure_mode="unavailable",
                    **provider_payload,
                )
            except Exception:
                logger.exception(
                    "provider_registry_failure_record_failed",
                    extra={"component": "persistence", "provider": DEFAULT_PROVIDER_NAME},
                )
        raise


def _validate_history(history: Any, symbol: str) -> pd.DataFrame:
    if history is None or not isinstance(history, pd.DataFrame) or history.empty or "Close" not in history.columns:
        raise MarketDataError(
            f"No historical price data returned for {symbol}.", status_code=404
        )
    cleaned = history.dropna(subset=["Close"]).copy()
    if cleaned.empty:
        raise MarketDataError(
            f"Historical price data for {symbol} has no valid close prices.",
            status_code=404,
        )
    return cleaned


def _acquire_history(
    symbol: str, settings: Any, provider_call_budget: int | None
) -> tuple[pd.DataFrame, str]:
    """Fetch daily price history from yfinance, falling back to Stooq.

    yfinance is web-scraped and breaks periodically (format changes, IP bans),
    so a second end-of-day source keeps scans alive when it fails. Budget
    exhaustion (429) is not retried against the fallback.
    """
    try:
        history = _with_retries(
            f"download market history for {symbol}",
            symbol,
            lambda: _download_history(symbol, settings.market_data_timeout_seconds),
            settings.market_data_max_attempts,
            settings.market_data_retry_backoff_seconds,
            before_attempt=lambda _: _consume_provider_call(
                provider_call_budget,
                symbol=symbol,
                action="download market history",
            ),
        )
        return _validate_history(history, symbol), DEFAULT_PROVIDER_NAME
    except MarketDataError as exc:
        if exc.status_code == 429:
            raise
        try:
            fallback = _validate_history(
                _download_history_alpha_vantage(
                    symbol,
                    settings.market_data_timeout_seconds,
                    getattr(settings, "alpha_vantage_api_key", None),
                ),
                symbol,
            )
        except Exception:
            raise exc
        logger.info(
            "market_data_provider_fallback",
            extra={
                "component": "market_data",
                "ticker": symbol,
                "provider": _FALLBACK_PROVIDER_NAME,
                "reason": str(exc),
            },
        )
        return fallback, _FALLBACK_PROVIDER_NAME


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
        # yfinance returns columns like ('Close', 'AAPL'); the ticker may sit on
        # either level depending on version, so drop whichever level holds it.
        if symbol in history.columns.get_level_values(-1):
            history = history.xs(symbol, axis=1, level=-1, drop_level=True)
        elif symbol in history.columns.get_level_values(0):
            history = history.xs(symbol, axis=1, level=0, drop_level=True)
        else:
            history = history.droplevel(-1, axis=1)
    return history if isinstance(history, pd.DataFrame) else pd.DataFrame()


_ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
_FALLBACK_PROVIDER_NAME = "alpha_vantage"
_FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"


def _finnhub_quote(symbol: str, timeout_seconds: float, api_key: str | None) -> float | None:
    """Return the latest real-time price from Finnhub's free /quote endpoint.

    Requires FINNHUB_API_KEY; without it this is a no-op returning None, so the
    price simply falls back to yfinance/history sources. Best-effort: any error
    yields None rather than failing the whole market-data fetch.
    """
    if not api_key:
        return None

    query = parse.urlencode({"symbol": symbol, "token": api_key})
    request = urlrequest.Request(
        f"{_FINNHUB_QUOTE_URL}?{query}",
        headers={"User-Agent": "stock-ai-assistant/1.0"},
    )
    try:
        with urlrequest.urlopen(request, timeout=max(1, int(timeout_seconds))) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except (urlerror.URLError, TimeoutError, ValueError):
        return None

    if not isinstance(payload, dict):
        return None
    price = _to_float(payload.get("c"))
    # Finnhub returns c=0 for unknown symbols or when no quote is available.
    if price is None or price <= 0:
        return None
    return price


def _download_history_alpha_vantage(
    symbol: str, timeout_seconds: float, api_key: str | None
) -> pd.DataFrame:
    """Fetch daily OHLCV history from Alpha Vantage as a yfinance fallback.

    Requires ALPHA_VANTAGE_API_KEY (free tier). Without a key this is a no-op
    that returns an empty DataFrame, so the fallback simply stays inactive.
    Returns a frame shaped like the yfinance one (DatetimeIndex with
    Open/High/Low/Close/Volume columns), or empty on any problem (including the
    free-tier rate-limit notice).
    """
    if not api_key:
        return pd.DataFrame()

    query = parse.urlencode(
        {
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            # compact = last 100 daily points (free tier; full is premium-only).
            # Enough for price/MA50/RSI; MA200 degrades gracefully to None.
            "outputsize": "compact",
            "datatype": "csv",
            "apikey": api_key,
        }
    )
    request = urlrequest.Request(
        f"{_ALPHA_VANTAGE_URL}?{query}",
        headers={"User-Agent": "stock-ai-assistant/1.0"},
    )
    try:
        with urlrequest.urlopen(request, timeout=max(1, int(timeout_seconds))) as response:
            raw = response.read().decode("utf-8", "replace")
    except (urlerror.URLError, TimeoutError, ValueError):
        return pd.DataFrame()

    # On rate limits / errors AV returns a JSON note instead of CSV.
    if not raw.strip().lower().startswith("timestamp"):
        return pd.DataFrame()

    try:
        frame = pd.read_csv(StringIO(raw))
    except (pd.errors.ParserError, ValueError):
        return pd.DataFrame()
    if frame.empty or "timestamp" not in frame.columns or "close" not in frame.columns:
        return pd.DataFrame()

    frame = frame.rename(
        columns={
            "timestamp": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce", utc=True)
    frame = frame.dropna(subset=["Date"]).set_index("Date").sort_index()
    keep = [column for column in ("Open", "High", "Low", "Close", "Volume") if column in frame.columns]
    return frame[keep]


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
    provider_call_budget: int | None,
) -> dict[str, Any]:
    try:
        info = _with_retries(
            f"load company profile for {symbol}",
            symbol,
            lambda: stock.info,
            attempts,
            retry_backoff_seconds,
            before_attempt=lambda _: _consume_provider_call(
                provider_call_budget,
                symbol=symbol,
                action="load company profile",
            ),
        )
    except MarketDataError as exc:
        if exc.status_code == 429:
            raise
        logger.warning("Using empty company profile for %s: %s", symbol, exc)
        return {}
    return info if isinstance(info, dict) else {}


def _safe_fast_info(
    stock: yf.Ticker,
    *,
    symbol: str,
    provider_call_budget: int | None,
) -> Any:
    try:
        _consume_provider_call(
            provider_call_budget,
            symbol=symbol,
            action="load fast info",
        )
        return stock.fast_info
    except MarketDataError:
        raise
    except Exception:
        return {}


def _with_retries(
    action: str,
    symbol: str,
    operation: Callable[[], T],
    attempts: int,
    retry_backoff_seconds: float,
    before_attempt: Callable[[int], None] | None = None,
) -> T:
    total_attempts = max(1, attempts)
    delay = max(0.0, retry_backoff_seconds)
    last_exc: Exception | None = None

    for attempt in range(1, total_attempts + 1):
        try:
            if before_attempt is not None:
                before_attempt(attempt)
            return operation()
        except MarketDataError:
            raise
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


def _consume_provider_call(
    provider_call_budget: int | None,
    *,
    symbol: str,
    action: str,
) -> None:
    try:
        consume_runtime_budget("provider_calls", provider_call_budget)
    except RuntimeBudgetExceeded as exc:
        raise MarketDataError(
            f"Provider call budget exhausted while trying to {action} for {symbol}: {exc}",
            status_code=429,
        ) from exc


def _market_data_cache_ttl_seconds(settings: Any, provider_profile: dict[str, Any]) -> int:
    ttl = getattr(settings, "market_data_cache_ttl_seconds", None)
    if ttl is None:
        ttl = provider_profile.get("cache_ttl_seconds") or 0
    return max(0, int(ttl))


def _get_cached_market_data(symbol: str, ttl_seconds: int) -> dict[str, Any] | None:
    if ttl_seconds <= 0:
        return None

    now = time.monotonic()
    with _MARKET_DATA_CACHE_LOCK:
        cached = _MARKET_DATA_CACHE.get(symbol)
        if cached is None:
            return None
        expires_at, market = cached
        if expires_at <= now:
            _MARKET_DATA_CACHE.pop(symbol, None)
            return None
        cached_market = _copy_market_data(market)

    cached_market["cache_hit"] = True
    return cached_market


def _set_cached_market_data(
    symbol: str,
    market: dict[str, Any],
    ttl_seconds: int,
) -> None:
    if ttl_seconds <= 0:
        return

    with _MARKET_DATA_CACHE_LOCK:
        _MARKET_DATA_CACHE[symbol] = (
            time.monotonic() + ttl_seconds,
            _copy_market_data(market),
        )


def _copy_market_data(market: dict[str, Any]) -> dict[str, Any]:
    copied = market.copy()
    history = copied.get("history")
    if isinstance(history, pd.DataFrame):
        copied["history"] = history.copy(deep=True)

    for key in ("info", "data_quality", "fx", "source_provenance"):
        value = copied.get(key)
        if isinstance(value, dict):
            copied[key] = value.copy()
    return copied


def clear_market_data_cache() -> None:
    with _MARKET_DATA_CACHE_LOCK:
        _MARKET_DATA_CACHE.clear()


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


def _build_event_calendar(*, info: dict[str, Any], fetched_at: datetime) -> dict[str, Any] | None:
    events: list[dict[str, Any]] = []
    earnings_dates = _extract_datetime_candidates(info.get("earningsDate"))
    earnings_timestamp = _coerce_datetime_like(info.get("earningsTimestamp"))
    if earnings_timestamp is not None:
        earnings_dates = earnings_dates or [earnings_timestamp]
    if earnings_dates:
        scheduled_at = min(earnings_dates)
        window_end_at = max(earnings_dates) if len(earnings_dates) > 1 else None
        events.append(
            {
                "name": "earnings",
                "scheduled_at": scheduled_at,
                "window_start_at": scheduled_at if len(earnings_dates) > 1 else None,
                "window_end_at": window_end_at,
                "note": "Derived from yfinance company profile earnings dates.",
            }
        )

    ex_dividend_dates = _extract_datetime_candidates(info.get("exDividendDate"))
    dividend_dates = _extract_datetime_candidates(info.get("dividendDate"))
    dividend_timestamp = _coerce_datetime_like(info.get("dividendDate"))
    next_dividend_at = min(ex_dividend_dates or dividend_dates or ([dividend_timestamp] if dividend_timestamp else []), default=None)
    if next_dividend_at is not None:
        events.append(
            {
                "name": "ex_dividend",
                "scheduled_at": next_dividend_at,
                "note": "Derived from yfinance company profile dividend dates.",
            }
        )

    if not events:
        return None

    summary_bits = []
    earnings_event = next((event for event in events if event["name"] == "earnings"), None)
    if earnings_event and earnings_event.get("scheduled_at") is not None:
        summary_bits.append(
            f"Next earnings around {earnings_event['scheduled_at'].date().isoformat()}"
        )
    dividend_event = next((event for event in events if event["name"] == "ex_dividend"), None)
    if dividend_event and dividend_event.get("scheduled_at") is not None:
        summary_bits.append(
            f"Next ex-dividend around {dividend_event['scheduled_at'].date().isoformat()}"
        )

    return {
        "summary": "; ".join(summary_bits) if summary_bits else "Company event calendar available from yfinance profile fields.",
        "upcoming_events": events,
        "fetched_at": fetched_at,
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


def _extract_datetime_candidates(value: Any) -> list[datetime]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    parsed: list[datetime] = []
    for item in values:
        dt_value = _coerce_datetime_like(item)
        if dt_value is not None:
            parsed.append(dt_value)
    return parsed


def _coerce_datetime_like(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt_value = value
    elif isinstance(value, pd.Timestamp):
        dt_value = value.to_pydatetime()
    elif isinstance(value, str) and value.strip():
        parsed = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(parsed):
            return None
        dt_value = parsed.to_pydatetime()
    else:
        return None

    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=timezone.utc)
    return dt_value.astimezone(timezone.utc)
