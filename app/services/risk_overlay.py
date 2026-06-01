"""Risk overlay for macro-aware portfolio management.

Adjusts risk tolerance and risk weighting based on macroeconomic conditions
and sector characteristics. This adds a second layer of risk management
on top of individual stock scores.

Logic:
- Growth/Tech stocks: higher risk when Fed raising rates (duration risk)
- High-dividend stocks: higher risk when inflation rising (real yield erosion)
- Cyclicals: higher risk when growth weak (earnings risk)
- Banks/Financials: lower risk when rates stable (net interest margin stable)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.macro_context import MacroContext
    from app.services.sector_sensitivity import SectorSensitivity


@dataclass(frozen=True)
class RiskOverlay:
    """Risk adjustment based on macro and sector context."""

    base_risk_score: float  # Original risk score from technicals (0-100)
    macro_risk_adjustment: float  # -20 to +20 points
    sector_risk_adjustment: float  # -20 to +20 points
    adjusted_risk_score: float  # Final risk score after adjustments
    risk_flag: str | None  # "high_growth_rates_rising", "high_dividend_inflation", etc.


def calculate_risk_overlay(
    base_risk_score: float,
    macro_context: MacroContext | None = None,
    sector_sensitivity: SectorSensitivity | None = None,
    dividend_yield: float | None = None,
) -> RiskOverlay:
    """Calculate risk overlay based on macro and sector context.

    Args:
        base_risk_score: Original risk score from technical analysis (0-100)
        macro_context: Current macro conditions (volatility, rates, inflation)
        sector_sensitivity: Sector's sensitivity to macro factors
        dividend_yield: Stock's dividend yield (for dividend stocks)

    Returns:
        RiskOverlay with adjusted risk score and explanations
    """
    macro_adj = 0.0
    sector_adj = 0.0
    risk_flag = None

    # Macro-based risk adjustments
    if macro_context:
        macro_adj, macro_flag = _macro_risk_adjustment(macro_context)
        if macro_flag:
            risk_flag = macro_flag

    # Sector-based risk adjustments (combine with macro)
    if sector_sensitivity and macro_context:
        sector_adj, sector_flag = _sector_risk_adjustment(
            sector_sensitivity, macro_context, dividend_yield
        )
        if sector_flag and not risk_flag:
            risk_flag = sector_flag

    # Combine adjustments and clamp to valid range
    total_adjustment = macro_adj + sector_adj
    adjusted_risk = min(100.0, max(0.0, base_risk_score + total_adjustment))

    return RiskOverlay(
        base_risk_score=round(base_risk_score, 1),
        macro_risk_adjustment=round(macro_adj, 1),
        sector_risk_adjustment=round(sector_adj, 1),
        adjusted_risk_score=round(adjusted_risk, 1),
        risk_flag=risk_flag,
    )


def _macro_risk_adjustment(macro_context: MacroContext) -> tuple[float, str | None]:
    """Calculate risk adjustment based on macro conditions.

    Returns:
        Tuple of (adjustment_points, risk_flag)
    """
    adjustment = 0.0
    flag = None

    # High volatility increases risk
    if macro_context.volatility_level == "high":
        adjustment += 10.0
        flag = "high_macro_volatility"

    # Rising rates increase risk for growth/duration-sensitive assets
    if macro_context.rate_direction == "rising":
        adjustment += 8.0
        if not flag:
            flag = "rising_rates_risk"

    # Elevated inflation increases risk (real value erosion)
    if macro_context.inflation_level == "elevated":
        adjustment += 7.0
        if not flag:
            flag = "elevated_inflation_risk"

    # Falling rates decrease risk (easier valuations)
    if macro_context.rate_direction == "falling":
        adjustment -= 5.0

    return adjustment, flag


def _sector_risk_adjustment(
    sector_sensitivity: SectorSensitivity,
    macro_context: MacroContext,
    dividend_yield: float | None = None,
) -> tuple[float, str | None]:
    """Calculate sector-specific risk adjustment.

    Returns:
        Tuple of (adjustment_points, risk_flag)
    """
    adjustment = 0.0
    flag = None

    # Tech/Growth suffering from rising rates
    if (
        sector_sensitivity.fed_rate_sensitivity < -0.5
        and macro_context.rate_direction == "rising"
    ):
        adjustment += 12.0
        flag = "growth_stock_rising_rates"

    # Financials benefiting from rising rates = lower risk
    elif (
        sector_sensitivity.fed_rate_sensitivity > 0.4
        and macro_context.rate_direction == "rising"
    ):
        adjustment -= 8.0

    # Energy benefiting from inflation = lower risk
    if (
        sector_sensitivity.inflation_sensitivity > 0.6
        and macro_context.inflation_level == "elevated"
    ):
        adjustment -= 6.0

    # Utilities suffering from rising rates + inflation
    if (
        sector_sensitivity.fed_rate_sensitivity < -0.5
        and sector_sensitivity.inflation_sensitivity < -0.2
    ):
        if macro_context.rate_direction == "rising":
            adjustment += 10.0
            flag = "utility_rising_rates"
        if macro_context.inflation_level == "elevated":
            adjustment += 5.0

    # High-dividend stocks at risk when inflation rising (real yield compression)
    if dividend_yield is not None and dividend_yield > 2.0:
        if macro_context.inflation_level == "elevated":
            adjustment += 8.0
            flag = "high_dividend_inflation_risk"

    return adjustment, flag


def risk_overlay_notes(overlay: RiskOverlay) -> list[str]:
    """Generate human-readable notes about risk overlay.

    Args:
        overlay: RiskOverlay with adjustments

    Returns:
        List of explanatory notes
    """
    notes: list[str] = []

    if overlay.adjusted_risk_score > overlay.base_risk_score + 2:
        notes.append(
            f"⚠️ Risk elevated: base {overlay.base_risk_score} → "
            f"{overlay.adjusted_risk_score} due to macro headwinds."
        )
    elif overlay.adjusted_risk_score < overlay.base_risk_score - 2:
        notes.append(
            f"✓ Risk reduced: base {overlay.base_risk_score} → "
            f"{overlay.adjusted_risk_score} due to favorable macro."
        )

    if overlay.risk_flag:
        flag_descriptions = {
            "high_macro_volatility": "High macro volatility increases market risk.",
            "rising_rates_risk": "Rising rates pressuring long-duration assets.",
            "elevated_inflation_risk": "Elevated inflation eroding real values.",
            "growth_stock_rising_rates": "Growth/tech stocks under pressure from rising rates.",
            "utility_rising_rates": "Utilities sensitive to rate increases (dividend impact).",
            "high_dividend_inflation_risk": "High dividend yields at risk from inflation (real yield compression).",
        }
        desc = flag_descriptions.get(overlay.risk_flag)
        if desc:
            notes.append(desc)

    return notes
