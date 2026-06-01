"""Economic data surprise detection and alert generation.

Tracks when economic events release with actual values different from expectations.
Calculates surprise magnitude and generates alerts for trading-relevant surprises.

Example surprises:
- CPI expected 0.3%, actual 0.1% → -66.7% surprise (deflationary surprise)
- Jobs expected 200k, actual 150k → -25% surprise (weak labor market)
- Fed maintains rate (expected), but hawkish guidance (unexpected) → qualitative surprise
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from typing import Any


@dataclass(frozen=True)
class EconomicSurprise:
    """A surprise in an economic data release."""

    event_type: str  # "jobs", "cpi", "ppi", "gdp", "pce", "fomc", etc.
    event_date: date
    event_name: str  # "CPI Release (Jan)", "Jobs Report"
    expected: float | None  # Expected value
    actual: float | None  # Actual value
    previous: float | None  # Previous value (for context)
    surprise_pct: float | None  # (actual - expected) / expected * 100
    surprise_magnitude: str  # "low", "medium", "high", "extreme"
    direction: str  # "positive", "negative", "mixed", "none"
    trading_relevant: bool  # Should this trigger an alert?
    description: str  # Human-readable description


def calculate_surprise(
    event_type: str,
    event_name: str,
    expected: float | None,
    actual: float | None,
    previous: float | None = None,
    event_date: date | None = None,
) -> EconomicSurprise:
    """Calculate surprise magnitude for an economic event.

    Args:
        event_type: Type of event (jobs, cpi, ppi, gdp, etc.)
        event_name: Human-readable name
        expected: Expected value
        actual: Actual released value
        previous: Previous reading (for context)
        event_date: Date of event

    Returns:
        EconomicSurprise with calculated metrics
    """
    if event_date is None:
        event_date = date.today()

    surprise_pct = None
    direction = "none"
    magnitude = "low"
    trading_relevant = False
    description = ""

    # Calculate surprise
    if expected is not None and actual is not None:
        if expected == 0:
            surprise_pct = None
            direction = "none"
        else:
            # For very small expected values (inflation), use absolute difference in basis points
            # For larger values (employment), use percentage
            if abs(expected) < 1:
                # inflation/yield data: measure in basis points or basis point % of expected
                # Keep sign!
                diff = (actual - expected)
                # Convert to percentage: (0.2% point difference / 0.3% expected) * 100
                surprise_pct = (diff / abs(expected)) * 100
            else:
                # employment, GDP etc: standard percentage calculation
                surprise_pct = ((actual - expected) / abs(expected)) * 100

            direction = "positive" if actual > expected else "negative"

        # Magnitude thresholds - different for different event types
        if surprise_pct is not None:
            abs_surprise = abs(surprise_pct)
        else:
            abs_surprise = 0

        if event_type in {"cpi", "ppi", "pce", "inflation"}:
            # For inflation, thresholds are lower (basis point surprises matter more)
            if abs_surprise > 50:
                magnitude = "extreme"
                trading_relevant = True
            elif abs_surprise > 25:
                magnitude = "high"
                trading_relevant = True
            elif abs_surprise > 10:
                magnitude = "medium"
                trading_relevant = True
        else:
            # For employment, GDP, etc.
            if abs_surprise > 20:
                magnitude = "extreme"
                trading_relevant = True
            elif abs_surprise > 10:
                magnitude = "high"
                trading_relevant = True
            elif abs_surprise > 5:
                magnitude = "medium"
                trading_relevant = True

        # Build description
        if surprise_pct > 0:
            desc_dir = "beat expectations"
        else:
            desc_dir = "missed expectations"

        description = (
            f"{event_name}: expected {expected}, actual {actual} "
            f"({desc_dir}, {abs_surprise:.1f}% surprise)"
        )
    else:
        description = f"{event_name}: expected {expected}, actual {actual}"

    return EconomicSurprise(
        event_type=event_type,
        event_date=event_date,
        event_name=event_name,
        expected=expected,
        actual=actual,
        previous=previous,
        surprise_pct=round(surprise_pct, 1) if surprise_pct is not None else None,
        surprise_magnitude=magnitude,
        direction=direction,
        trading_relevant=trading_relevant,
        description=description,
    )


def alert_text(surprise: EconomicSurprise) -> str | None:
    """Generate alert text for a trading-relevant surprise.

    Returns:
        Alert text if surprise is trading_relevant, None otherwise
    """
    if not surprise.trading_relevant or surprise.surprise_pct is None:
        return None

    emoji_map = {
        "extreme": "🚨",
        "high": "⚠️",
        "medium": "📊",
    }
    emoji = emoji_map.get(surprise.surprise_magnitude, "")

    market_impact = _market_impact_text(surprise)
    return (
        f"{emoji} {surprise.event_name}\n"
        f"Expected: {surprise.expected}, Actual: {surprise.actual}\n"
        f"Surprise: {surprise.surprise_pct:+.1f}% ({surprise.surprise_magnitude})\n"
        f"\n{market_impact}"
    )


def _market_impact_text(surprise: EconomicSurprise) -> str:
    """Describe likely market impact."""
    impacts = {
        "jobs": {
            "positive": "Strong jobs → equity support, slight USD strength, rate expectations up",
            "negative": "Weak jobs → equity pressure, USD weakness, rate cut bets increase",
        },
        "cpi": {
            "positive": "Higher inflation → USD support, bond yields up, growth stocks pressure",
            "negative": "Lower inflation → bond yields down, growth stocks support, USD pressure",
        },
        "ppi": {
            "positive": "Higher producer inflation → commodity support, energy strength",
            "negative": "Lower PPI → commodity pressure, energy weakness",
        },
        "gdp": {
            "positive": "Strong growth → equity support, rates likely higher",
            "negative": "Weak growth → equity pressure, rate cut bets",
        },
        "fomc": {
            "positive": "Hawkish (rates stay high) → USD strength, bond yields up, tech pressure",
            "negative": "Dovish (cuts expected) → USD weakness, yields down, growth support",
        },
    }

    event_impacts = impacts.get(surprise.event_type, {})
    direction_key = "positive" if surprise.direction == "positive" else "negative"
    return event_impacts.get(direction_key, "Market impact TBD")


def surprise_alert_summary(surprises: list[EconomicSurprise]) -> list[str]:
    """Generate summary alerts from a list of surprises.

    Args:
        surprises: List of economic surprises

    Returns:
        List of alert texts for trading-relevant surprises
    """
    trading_relevant = [s for s in surprises if s.trading_relevant]
    if not trading_relevant:
        return []

    alerts = []
    for surprise in sorted(
        trading_relevant, key=lambda s: abs(s.surprise_pct or 0), reverse=True
    ):
        alert = alert_text(surprise)
        if alert:
            alerts.append(alert)

    return alerts
