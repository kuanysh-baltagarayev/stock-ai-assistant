"""Broad U.S. market regime context.

Stops analyzing a ticker in complete isolation by adding a deterministic,
testable read on the overall U.S. market backdrop: index trend, volatility
regime, rates backdrop, sector rotation, and an aggregate risk appetite.

Design notes:
- ``build_market_regime`` is pure: it works from offline price fixtures and
  never touches the network, so it is fully testable.
- ``collect_market_regime`` is the network-facing wrapper around yfinance. It
  is best-effort: any missing input degrades ``confidence`` instead of raising,
  and a total failure returns an "unknown" regime rather than breaking analysis.
- Regime is intended to be *context*, not a dominant signal. Scoring should
  apply it within tightly capped bounds.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

REGIME_PROVIDER_NAME = "yfinance"
REGIME_SOURCE_URL = "https://finance.yahoo.com"
REGIME_DATA_CATEGORY = "market_regime"
REGIME_PARSER_VERSION = "market-regime-v1"

# Index proxies and a small, fixed set of sector ETFs split into cyclical
# (risk-on) and defensive (risk-off) buckets. Relative strength between the two
# buckets is a cheap, transparent read on sector rotation.
INDEX_SYMBOLS = ("SPY", "QQQ")
VIX_SYMBOL = "^VIX"
TEN_YEAR_SYMBOL = "^TNX"  # CBOE 10Y Treasury yield index (yield * 10)
CYCLICAL_ETFS = ("XLK", "XLY", "XLF")  # tech, discretionary, financials
DEFENSIVE_ETFS = ("XLP", "XLU", "XLV")  # staples, utilities, health care

# Trading-day windows used for trend and relative-strength reads.
_SHORT_WINDOW = 21   # ~1 month
_MEDIUM_WINDOW = 63  # ~3 months

UNKNOWN = "unknown"


@dataclass(frozen=True)
class MarketRegime:
    """Deterministic snapshot of the broad U.S. market backdrop."""

    reference_date: datetime
    index_trend: str        # "uptrend", "downtrend", "sideways", "unknown"
    volatility_regime: str  # "low", "normal", "elevated", "high", "unknown"
    rates_backdrop: str     # "rising", "falling", "stable", "unknown"
    sector_rotation: str    # "risk_on", "risk_off", "mixed", "unknown"
    risk_appetite: str      # "risk_on", "risk_off", "mixed", "unknown"
    confidence: float       # 0.0 - 1.0
    source_provenance: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def is_known(self) -> bool:
        return self.confidence > 0.0 and self.risk_appetite != UNKNOWN


def build_market_regime(
    reference_date: datetime,
    *,
    index_closes: dict[str, list[float]] | None = None,
    vix_values: list[float] | None = None,
    yield_values: list[float] | None = None,
    sector_returns: dict[str, float] | None = None,
    source_provenance: dict[str, Any] | None = None,
) -> MarketRegime:
    """Build a market regime from raw price inputs.

    Args:
        reference_date: Analysis timestamp.
        index_closes: Oldest-first daily closes per index symbol (e.g. SPY, QQQ).
        vix_values: Oldest-first VIX closes; the latest point sets the regime.
        yield_values: Oldest-first 10Y yield proxy values; trend sets backdrop.
        sector_returns: Per-ETF trailing return (fraction, e.g. 0.04 = +4%) used
            for cyclical-vs-defensive relative strength.
        source_provenance: Optional provenance metadata to attach.

    Returns:
        A ``MarketRegime``. Missing inputs lower ``confidence`` rather than
        raising; a fully empty input set yields an "unknown" regime.
    """
    index_closes = index_closes or {}
    sector_returns = sector_returns or {}

    # Confidence starts full and is debited per missing/insufficient component.
    confidence = 1.0
    notes: list[str] = []

    index_trend, index_conf_penalty, index_note = _infer_index_trend(index_closes)
    confidence -= index_conf_penalty
    if index_note:
        notes.append(index_note)

    volatility_regime, vol_penalty, vol_note = _infer_volatility_regime(vix_values)
    confidence -= vol_penalty
    if vol_note:
        notes.append(vol_note)

    rates_backdrop, rates_penalty, rates_note = _infer_rates_backdrop(yield_values)
    confidence -= rates_penalty
    if rates_note:
        notes.append(rates_note)

    sector_rotation, rotation_penalty, rotation_note = _infer_sector_rotation(sector_returns)
    confidence -= rotation_penalty
    if rotation_note:
        notes.append(rotation_note)

    risk_appetite = _infer_risk_appetite(
        index_trend, volatility_regime, sector_rotation
    )

    confidence = round(max(0.0, min(1.0, confidence)), 2)
    if risk_appetite == UNKNOWN:
        confidence = 0.0

    return MarketRegime(
        reference_date=reference_date,
        index_trend=index_trend,
        volatility_regime=volatility_regime,
        rates_backdrop=rates_backdrop,
        sector_rotation=sector_rotation,
        risk_appetite=risk_appetite,
        confidence=confidence,
        source_provenance=source_provenance or {},
        notes=tuple(notes),
    )


def market_regime_summary(regime: MarketRegime | None) -> list[str]:
    """Return a short, user-facing note about the market regime.

    Returns an empty list when no usable regime is available so callers can add
    the line conditionally.
    """
    if regime is None or not regime.is_known:
        return []

    appetite_label = {
        "risk_on": "risk-on",
        "risk_off": "risk-off",
        "mixed": "mixed",
    }.get(regime.risk_appetite, regime.risk_appetite)

    source = (
        regime.source_provenance.get("provider_name")
        if isinstance(regime.source_provenance, dict)
        else None
    ) or REGIME_PROVIDER_NAME

    return [
        f"Market regime: {appetite_label}, confidence {regime.confidence:.2f} "
        f"(index {regime.index_trend}, volatility {regime.volatility_regime}, "
        f"rates {regime.rates_backdrop}; source {source})."
    ]


# --- inference helpers -----------------------------------------------------


def _infer_index_trend(
    index_closes: dict[str, list[float]],
) -> tuple[str, float, str | None]:
    """Infer index trend from SPY/QQQ short-vs-medium return.

    Returns (trend, confidence_penalty, note).
    """
    series = [
        [v for v in (index_closes.get(symbol) or []) if v is not None]
        for symbol in INDEX_SYMBOLS
    ]
    usable = [s for s in series if len(s) >= _SHORT_WINDOW + 1]
    if not usable:
        return UNKNOWN, 0.4, "Index trend unavailable (insufficient index history)."

    votes: list[str] = []
    for closes in usable:
        votes.append(_single_index_trend(closes))

    up = votes.count("uptrend")
    down = votes.count("downtrend")
    if up and not down:
        trend = "uptrend"
    elif down and not up:
        trend = "downtrend"
    elif up and down:
        trend = "sideways"
    else:
        trend = "sideways"

    # Slight penalty when we only had one of the two index proxies.
    penalty = 0.0 if len(usable) == len(INDEX_SYMBOLS) else 0.1
    note = None
    if penalty:
        note = "Index trend based on a partial index set; confidence reduced."
    return trend, penalty, note


def _single_index_trend(closes: list[float]) -> str:
    """Classify one index series using short and medium momentum."""
    latest = closes[-1]
    short_ref = closes[-(_SHORT_WINDOW + 1)]
    short_ret = (latest - short_ref) / short_ref if short_ref else 0.0

    medium_ret = 0.0
    if len(closes) >= _MEDIUM_WINDOW + 1:
        medium_ref = closes[-(_MEDIUM_WINDOW + 1)]
        medium_ret = (latest - medium_ref) / medium_ref if medium_ref else 0.0

    # ~2% over the month is the threshold to call a directional trend; smaller
    # moves are "sideways" to avoid reacting to noise.
    if short_ret > 0.02 and medium_ret >= 0.0:
        return "uptrend"
    if short_ret < -0.02 and medium_ret <= 0.0:
        return "downtrend"
    return "sideways"


def _infer_volatility_regime(
    vix_values: list[float] | None,
) -> tuple[str, float, str | None]:
    """Map the latest VIX value to a volatility regime bucket."""
    series = [v for v in (vix_values or []) if v is not None]
    if not series:
        return UNKNOWN, 0.25, "VIX unavailable; volatility regime unknown."

    vix = series[-1]
    if vix < 15:
        regime = "low"
    elif vix < 20:
        regime = "normal"
    elif vix < 30:
        regime = "elevated"
    else:
        regime = "high"
    return regime, 0.0, None


def _infer_rates_backdrop(
    yield_values: list[float] | None,
) -> tuple[str, float, str | None]:
    """Infer the rates backdrop from the 10Y yield proxy trend."""
    series = [v for v in (yield_values or []) if v is not None]
    if len(series) < 2:
        return UNKNOWN, 0.15, "10Y yield unavailable; rates backdrop unknown."

    recent = series[-1]
    earlier = series[0]
    delta = recent - earlier
    # ^TNX is yield * 10 (e.g. 42.0 == 4.20%). Use a ~0.15 point (1.5bps on the
    # raw yield) threshold so we ignore rounding noise. If callers pass the raw
    # yield instead, the threshold is conservative but still directional.
    if delta > 0.15:
        backdrop = "rising"
    elif delta < -0.15:
        backdrop = "falling"
    else:
        backdrop = "stable"
    return backdrop, 0.0, None


def _infer_sector_rotation(
    sector_returns: dict[str, float],
) -> tuple[str, float, str | None]:
    """Compare cyclical vs defensive sector returns for a rotation read."""
    cyclical = [
        sector_returns[s] for s in CYCLICAL_ETFS if sector_returns.get(s) is not None
    ]
    defensive = [
        sector_returns[s] for s in DEFENSIVE_ETFS if sector_returns.get(s) is not None
    ]
    if not cyclical or not defensive:
        return UNKNOWN, 0.2, "Sector rotation unavailable (insufficient ETF data)."

    cyc_avg = sum(cyclical) / len(cyclical)
    def_avg = sum(defensive) / len(defensive)
    spread = cyc_avg - def_avg
    # ~1.5% relative outperformance to call a rotation; otherwise "mixed".
    if spread > 0.015:
        rotation = "risk_on"
    elif spread < -0.015:
        rotation = "risk_off"
    else:
        rotation = "mixed"
    return rotation, 0.0, None


def _infer_risk_appetite(
    index_trend: str,
    volatility_regime: str,
    sector_rotation: str,
) -> str:
    """Aggregate the components into an overall risk appetite read.

    Uses a simple vote across the three available components. Returns "unknown"
    only when nothing is usable.
    """
    score = 0
    votes = 0

    if index_trend == "uptrend":
        score += 1
        votes += 1
    elif index_trend == "downtrend":
        score -= 1
        votes += 1
    elif index_trend == "sideways":
        votes += 1

    if volatility_regime in {"low", "normal"}:
        score += 1
        votes += 1
    elif volatility_regime in {"elevated", "high"}:
        score -= 1
        votes += 1

    if sector_rotation == "risk_on":
        score += 1
        votes += 1
    elif sector_rotation == "risk_off":
        score -= 1
        votes += 1
    elif sector_rotation == "mixed":
        votes += 1

    if votes == 0:
        return UNKNOWN
    if score > 0:
        return "risk_on"
    if score < 0:
        return "risk_off"
    return "mixed"


# --- network-facing collector ----------------------------------------------


def collect_market_regime(
    reference_date: datetime | None = None,
    *,
    enabled: bool = False,
    timeout: float = 20.0,
) -> MarketRegime:
    """Fetch market-regime inputs from yfinance and build a regime.

    Best-effort and side-effect-light: when ``enabled`` is False (the default),
    no network call is made and an "unknown", zero-confidence regime is
    returned so analysis is unaffected. Any fetch failure degrades confidence
    rather than raising.
    """
    ref = reference_date or datetime.now(timezone.utc)
    if not enabled:
        return MarketRegime(
            reference_date=ref,
            index_trend=UNKNOWN,
            volatility_regime=UNKNOWN,
            rates_backdrop=UNKNOWN,
            sector_rotation=UNKNOWN,
            risk_appetite=UNKNOWN,
            confidence=0.0,
            source_provenance={"provider_name": REGIME_PROVIDER_NAME},
            notes=("Market regime disabled.",),
        )

    symbols = (
        list(INDEX_SYMBOLS)
        + [VIX_SYMBOL, TEN_YEAR_SYMBOL]
        + list(CYCLICAL_ETFS)
        + list(DEFENSIVE_ETFS)
    )
    closes = _download_regime_closes(symbols, timeout=timeout)

    index_closes = {sym: closes.get(sym, []) for sym in INDEX_SYMBOLS}
    vix_values = closes.get(VIX_SYMBOL, [])
    yield_values = closes.get(TEN_YEAR_SYMBOL, [])
    sector_returns = {
        sym: _trailing_return(closes.get(sym, []), _MEDIUM_WINDOW)
        for sym in CYCLICAL_ETFS + DEFENSIVE_ETFS
        if _trailing_return(closes.get(sym, []), _MEDIUM_WINDOW) is not None
    }

    return build_market_regime(
        ref,
        index_closes=index_closes,
        vix_values=vix_values,
        yield_values=yield_values,
        sector_returns=sector_returns,
        source_provenance={
            "provider_name": REGIME_PROVIDER_NAME,
            "source_url": REGIME_SOURCE_URL,
            "data_category": REGIME_DATA_CATEGORY,
            "parser_version": REGIME_PARSER_VERSION,
        },
    )


def _trailing_return(closes: list[float], window: int) -> float | None:
    series = [v for v in (closes or []) if v is not None]
    if len(series) < window + 1:
        return None
    ref = series[-(window + 1)]
    if not ref:
        return None
    return (series[-1] - ref) / ref


def _download_regime_closes(
    symbols: list[str], *, timeout: float
) -> dict[str, list[float]]:
    """Download oldest-first daily closes per symbol via yfinance.

    Returns a dict mapping symbol -> close list. Symbols that fail simply map to
    an empty list, which the regime builder treats as a confidence penalty.
    """
    result: dict[str, list[float]] = {}
    try:
        import yfinance as yf  # imported lazily so the module stays import-safe
    except Exception as exc:  # pragma: no cover - yfinance always present in app
        logger.warning(
            "market_regime_yfinance_import_failed",
            extra={"component": "market_regime", "error": str(exc)},
        )
        return result

    try:
        data = yf.download(
            symbols,
            period="6mo",
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
            group_by="ticker",
            timeout=max(1, int(timeout)),
        )
    except Exception as exc:
        logger.warning(
            "market_regime_download_failed",
            extra={"component": "market_regime", "error": str(exc)},
        )
        return result

    for symbol in symbols:
        result[symbol] = _extract_symbol_closes(data, symbol)
    return result


def _extract_symbol_closes(data: Any, symbol: str) -> list[float]:
    """Pull a clean oldest-first list of closes for one symbol from yf output."""
    try:
        import pandas as pd

        if data is None or not isinstance(data, pd.DataFrame) or data.empty:
            return []

        series = None
        if isinstance(data.columns, pd.MultiIndex):
            if (symbol, "Close") in data.columns:
                series = data[(symbol, "Close")]
            elif ("Close", symbol) in data.columns:
                series = data[("Close", symbol)]
        elif "Close" in data.columns:
            # Single-symbol download returns a flat frame.
            series = data["Close"]

        if series is None:
            return []
        return [float(v) for v in series.dropna().tolist()]
    except Exception as exc:
        logger.debug(
            "market_regime_extract_failed",
            extra={"component": "market_regime", "symbol": symbol, "error": str(exc)},
        )
        return []
