"""Sector-level macroeconomic sensitivity analysis.

Different sectors respond differently to macro conditions:
- Tech: sensitive to Fed rates (duration/valuation compression)
- Financials: sensitive to yield curve (net interest margin)
- Energy: sensitive to USD and commodity prices
- Utilities: sensitive to rates and inflation (dividend yields)
- Industrials: sensitive to economic growth and rates
- Healthcare: less sensitive to rates, more to regulations
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SectorSensitivity:
    """Macro sensitivity profile for a sector."""

    sector: str
    fed_rate_sensitivity: float  # -1.0 to 1.0: how much sector moves with rates
    inflation_sensitivity: float  # -1.0 to 1.0: how much sector moves with inflation
    growth_sensitivity: float  # 0.0 to 1.0: how much sector depends on GDP growth
    usd_sensitivity: float  # -1.0 to 1.0: correlation with USD strength
    description: str


# Sector sensitivity profiles (based on historical correlations)
_SECTOR_PROFILES: dict[str, SectorSensitivity] = {
    "Technology": SectorSensitivity(
        sector="Technology",
        fed_rate_sensitivity=-0.9,  # Highly negative: rising rates hurt valuations
        inflation_sensitivity=-0.3,  # Slightly negative: inflation not ideal
        growth_sensitivity=0.7,  # Depends on growth (software, cloud, etc.)
        usd_sensitivity=-0.2,  # Weak negative: some export exposure
        description="Tech highly sensitive to Fed rates (valuation compression). "
        "Benefits from growth, hurt by rising rates.",
    ),
    "Financials": SectorSensitivity(
        sector="Financials",
        fed_rate_sensitivity=0.6,  # Positive: higher rates = higher net interest margin
        inflation_sensitivity=0.2,  # Slightly positive
        growth_sensitivity=0.5,  # Moderate: loan demand depends on growth
        usd_sensitivity=0.3,  # Positive: USD strength helps US banks
        description="Banks benefit from rising rates and higher yield curves. "
        "Sensitive to economic growth for loan quality.",
    ),
    "Energy": SectorSensitivity(
        sector="Energy",
        fed_rate_sensitivity=-0.1,  # Low: commodity-driven more than rate-driven
        inflation_sensitivity=0.8,  # High positive: inflation pushes oil prices
        growth_sensitivity=0.6,  # Moderate: growth drives energy demand
        usd_sensitivity=-0.7,  # Strong negative: oil priced in USD
        description="Energy tied to oil prices and USD strength. "
        "Benefits from inflation and growth, hurt by strong dollar.",
    ),
    "Utilities": SectorSensitivity(
        sector="Utilities",
        fed_rate_sensitivity=-0.7,  # Negative: rising rates hurt dividend yields
        inflation_sensitivity=0.3,  # Slight positive: can pass costs to customers
        growth_sensitivity=0.1,  # Low: demand relatively stable
        usd_sensitivity=0.0,  # Neutral: domestic focus
        description="Utilities are rate-sensitive due to dividend nature. "
        "Stable growth, hurt by rising rates and inflation pressures.",
    ),
    "Industrials": SectorSensitivity(
        sector="Industrials",
        fed_rate_sensitivity=-0.4,  # Moderate negative: capex sensitivity
        inflation_sensitivity=-0.2,  # Slightly negative: cost pressure
        growth_sensitivity=0.8,  # High: strong GDP correlation
        usd_sensitivity=0.2,  # Slight positive: export competitiveness
        description="Industrials cycle with economic growth. "
        "Sensitive to capex cycle (rates) and commodity costs.",
    ),
    "Consumer Discretionary": SectorSensitivity(
        sector="Consumer Discretionary",
        fed_rate_sensitivity=-0.5,  # Moderate: affects consumer borrowing
        inflation_sensitivity=-0.4,  # Negative: erodes consumer purchasing power
        growth_sensitivity=0.7,  # High: depends on consumer confidence
        usd_sensitivity=0.1,  # Low: mixed (imports vs exports)
        description="Consumer discretionary highly dependent on growth and rates. "
        "Hurt by inflation (consumer margins) and rising rates.",
    ),
    "Consumer Staples": SectorSensitivity(
        sector="Consumer Staples",
        fed_rate_sensitivity=-0.2,  # Low: less rate-sensitive
        inflation_sensitivity=0.4,  # Moderate: can pass costs through
        growth_sensitivity=0.2,  # Low: staples demand stable
        usd_sensitivity=0.0,  # Neutral: domestic
        description="Consumer staples defensive, less rate-sensitive. "
        "Can tolerate inflation better than discretionary.",
    ),
    "Healthcare": SectorSensitivity(
        sector="Healthcare",
        fed_rate_sensitivity=-0.3,  # Low: structural growth offsetts rate pressure
        inflation_sensitivity=0.5,  # Moderate: drug prices can adjust
        growth_sensitivity=0.4,  # Moderate: aging population offset by efficiency
        usd_sensitivity=-0.1,  # Low negative: some pharma export exposure
        description="Healthcare defensive with structural growth. "
        "Less sensitive to macro cycles than growth/cyclicals.",
    ),
}


def get_sector_sensitivity(sector: str | None) -> SectorSensitivity | None:
    """Get sensitivity profile for a sector.

    Args:
        sector: Sector name (e.g., "Technology", "Financials")

    Returns:
        SectorSensitivity if sector found, None otherwise
    """
    if not sector:
        return None
    return _SECTOR_PROFILES.get(sector.strip())


def macro_impact_notes(
    sector: str | None,
    fed_rate_direction: str | None = None,
    inflation_level: str | None = None,
    growth_outlook: str | None = None,
) -> list[str]:
    """Generate notes about how macro conditions affect this sector.

    Args:
        sector: Sector name
        fed_rate_direction: "rising", "falling", "stable", or None
        inflation_level: "elevated", "moderate", "low", or None
        growth_outlook: "strong", "moderate", "weak", or None

    Returns:
        List of human-readable notes
    """
    sensitivity = get_sector_sensitivity(sector)
    if not sensitivity:
        return []

    notes: list[str] = []

    # Fed rate impact
    if fed_rate_direction == "rising" and sensitivity.fed_rate_sensitivity < -0.5:
        notes.append(
            f"{sector} is highly sensitive to rising rates "
            "(valuation/duration pressure). Consider defensive positioning."
        )
    elif fed_rate_direction == "falling" and sensitivity.fed_rate_sensitivity < 0:
        notes.append(
            f"{sector} typically benefits from falling rates. "
            "Favorable tailwind for valuations."
        )
    elif fed_rate_direction == "rising" and sensitivity.fed_rate_sensitivity > 0.4:
        notes.append(
            f"{sector} benefits from rising rates (e.g., wider margins). "
            "Favorable conditions."
        )

    # Inflation impact
    if inflation_level == "elevated":
        if sensitivity.inflation_sensitivity < -0.3:
            notes.append(
                f"{sector} struggles with high inflation (cost pressures). "
                "Monitor margin compression."
            )
        elif sensitivity.inflation_sensitivity > 0.4:
            notes.append(
                f"{sector} can pass inflation to customers. "
                "May benefit from pricing power."
            )

    # Growth impact
    if growth_outlook == "weak" and sensitivity.growth_sensitivity > 0.6:
        notes.append(
            f"{sector} is economically sensitive. "
            "Weak growth outlook is a headwind."
        )
    elif growth_outlook == "strong" and sensitivity.growth_sensitivity > 0.6:
        notes.append(
            f"{sector} benefits from strong growth. "
            "Favorable environment for earnings expansion."
        )

    return notes


def sector_macro_heat_map() -> dict[str, dict[str, float]]:
    """Return a heat map of sector sensitivities.

    Useful for understanding which sectors are most/least exposed
    to current macro conditions.

    Returns:
        Dict mapping sector names to sensitivity metrics
    """
    result = {}
    for profile in _SECTOR_PROFILES.values():
        result[profile.sector] = {
            "fed_rate": profile.fed_rate_sensitivity,
            "inflation": profile.inflation_sensitivity,
            "growth": profile.growth_sensitivity,
            "usd": profile.usd_sensitivity,
        }
    return result
