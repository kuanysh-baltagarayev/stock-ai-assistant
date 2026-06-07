from __future__ import annotations

from typing import Any


_CRITICAL_SOURCES = frozenset({"market_data"})
_OPTIONAL_SOURCES = frozenset({"sec_filings", "news", "macro_context", "market_regime"})


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


# ── per-analysis source coverage summary ──────────────────────────────

_SOURCE_LABELS: dict[str, str] = {
    "market_data": "рыночные данные",
    "sec_filings": "SEC filings",
    "news": "новости",
    "macro_context": "макро-контекст",
    "market_regime": "рыночный режим",
}


def build_coverage_summary(
    *,
    has_sec_filings: bool = False,
    cik_available: bool = False,
    has_news: bool = False,
    has_macro_context: bool = False,
    has_market_regime: bool = False,
    provider_name: str | None = None,
    source_tier: str | None = None,
    stale: bool = False,
    delayed: bool = False,
    missing: bool = False,
    source_disagreed: bool = False,
    confidence: float | None = None,
) -> dict[str, Any]:
    """Build a source-coverage summary for a single analysis.

    Returns a dict with keys:
      - ``present_sources`` — names of sources expected and present
      - ``missing_critical`` — critical sources (e.g. market data) that
        are absent (should never happen in normal flow)
      - ``missing_optional`` — optional sources that were not available
      - ``degradation_flags`` — stale, delayed, missing, source_disagreed
      - ``confidence`` — numeric confidence from data_quality
      - ``provider_summary`` — short ``provider/tier`` string
      - ``overall`` — one of ``full``, ``partial``, ``minimal``
    """
    expected_critical = set(_CRITICAL_SOURCES)
    expected_optional = set(_OPTIONAL_SOURCES)
    if not cik_available:
        expected_optional.discard("sec_filings")

    present: set[str] = {"market_data"}
    if has_sec_filings or (has_sec_filings and cik_available):
        present.add("sec_filings")
    if has_news:
        present.add("news")
    if has_macro_context:
        present.add("macro_context")
    if has_market_regime:
        present.add("market_regime")

    missing_critical = sorted(expected_critical - present)
    missing_optional = sorted(expected_optional - present)

    degradation_flags: list[str] = []
    if stale:
        degradation_flags.append("устаревшие данные")
    if delayed:
        degradation_flags.append("задержка данных")
    if missing:
        degradation_flags.append("неполные данные")
    if source_disagreed:
        degradation_flags.append("источники расходятся")

    if confidence is not None and confidence < 0.8:
        degradation_flags.append("пониженная уверенность")

    if missing_critical:
        overall = "minimal"
    elif missing_optional and confidence is not None and confidence < 0.7:
        overall = "partial"
    elif not missing_optional:
        overall = "full"
    else:
        overall = "partial"

    provider_summary = f"{provider_name or 'unknown'}/{source_tier or 'unknown'}"

    return {
        "present_sources": sorted(present),
        "missing_critical": missing_critical,
        "missing_optional": missing_optional,
        "degradation_flags": degradation_flags,
        "confidence": confidence,
        "provider_summary": provider_summary,
        "overall": overall,
    }


def format_coverage_gap_line(coverage: dict[str, Any] | None) -> str | None:
    """Return a compact one-line source-gap summary for Telegram output.

    Returns ``None`` when coverage data is missing (no gap information).
    Example: *"Покрытие: частичное (нет новостей, макро-контекста)"*
    """
    if not coverage:
        return None

    overall = coverage.get("overall", "unknown")
    labels = {
        "full": "полное",
        "partial": "частичное",
        "minimal": "минимальное",
    }
    label = labels.get(overall, overall)

    gaps: list[str] = []
    for source in coverage.get("missing_critical") or []:
        gaps.append(f"нет {_SOURCE_LABELS.get(source, source)} (критично)")
    for source in coverage.get("missing_optional") or []:
        gaps.append(f"нет {_SOURCE_LABELS.get(source, source)}")

    flags = coverage.get("degradation_flags") or []
    gap_text = ", ".join(gaps + flags[:2])
    if gap_text:
        return f"Покрытие: {label} ({gap_text})"
    return f"Покрытие: {label}"


def format_coverage_detail_lines(coverage: dict[str, Any] | None) -> list[str]:
    """Return multi-line detailed coverage summary for Telegram /risk view."""
    if not coverage:
        return []

    lines: list[str] = []
    present = coverage.get("present_sources") or []
    if present:
        present_labels = [_SOURCE_LABELS.get(s, s) for s in present]
        lines.append(f"Источники: {', '.join(present_labels)}")

    gaps: list[str] = []
    for source in coverage.get("missing_critical") or []:
        gaps.append(f"✗ {_SOURCE_LABELS.get(source, source)} (критический)")
    for source in coverage.get("missing_optional") or []:
        gaps.append(f"✗ {_SOURCE_LABELS.get(source, source)}")
    if gaps:
        lines.append("Отсутствуют: " + "; ".join(gaps))

    flags = coverage.get("degradation_flags") or []
    if flags:
        lines.append("Деградация: " + ", ".join(flags))

    overall = coverage.get("overall", "unknown")
    confidence = coverage.get("confidence")
    conf_text = f", уверенность {confidence:.2f}" if confidence is not None else ""
    lines.append(f"Общее покрытие: {overall}{conf_text}")
    return lines
