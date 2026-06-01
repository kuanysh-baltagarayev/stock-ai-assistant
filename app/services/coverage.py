from __future__ import annotations

def get_coverage_matrix() -> dict[str, list[str] | list[dict[str, str]]]:
    return {
        "supported_markets": [
            "U.S. listed equities on major exchanges",
            "Major U.S. ETFs",
            "Selected ADRs when the local listing distinction can be shown",
        ],
        "supported_asset_classes": [
            "U.S. equities",
            "U.S. ETFs",
            "selected ADRs",
        ],
        "source_tiers": [
            "Tier 1 official and open sources",
            "Tier 2 market-data providers and aggregators",
            "Tier 3 open web sources planned for future expansion",
        ],
        "calendars": [
            "U.S. trading sessions and market-hours freshness notes (NYSE/NASDAQ holidays and early closes)",
            "Company event hints from yfinance profile fields",
            "Weekly review, pre-market, market-open, midday, close, and after-hours digest modes",
        ],
        "currencies": [
            "USD is the primary trading currency in output",
            "Non-USD FX metadata is tracked",
            "Live FX conversion is not yet applied",
        ],
        "known_gaps": [
            "No live news ingestion yet",
            "Exchange calendar covers NYSE holidays/early-closes for 2025-2026 only; no automated feed yet",
            "Cross-listing mapping and provider aliases remain incomplete",
            "Live FX conversion provider is not wired in yet",
            "Open web collectors are not yet implemented",
        ],
    }


def format_coverage_lines(matrix: dict[str, list[str] | list[dict[str, str]]] | None = None) -> list[str]:
    data = matrix or get_coverage_matrix()
    lines: list[str] = []
    lines.append("Supported markets:")
    lines.extend(f"- {item}" for item in data["supported_markets"])
    lines.append("Supported asset classes:")
    lines.extend(f"- {item}" for item in data["supported_asset_classes"])
    lines.append("Source tiers:")
    lines.extend(f"- {item}" for item in data["source_tiers"])
    lines.append("Calendars:")
    lines.extend(f"- {item}" for item in data["calendars"])
    lines.append("Currencies:")
    lines.extend(f"- {item}" for item in data["currencies"])
    lines.append("Known gaps:")
    lines.extend(f"- {item}" for item in data["known_gaps"])
    return lines


def format_coverage_text(matrix: dict[str, list[str] | list[dict[str, str]]] | None = None) -> str:
    return "\n".join(format_coverage_lines(matrix))
