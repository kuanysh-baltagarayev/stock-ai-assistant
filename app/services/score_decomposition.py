from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas import DataQualityFlags, Scores


def _normalize_data_quality(dq: Any) -> DataQualityFlags:
    """Accept a ``DataQualityFlags`` instance or a plain dict."""
    if dq is None:
        return DataQualityFlags()
    if isinstance(dq, DataQualityFlags):
        return dq
    if isinstance(dq, dict):
        return DataQualityFlags(**{k: v for k, v in dq.items() if k in DataQualityFlags.model_fields})
    return DataQualityFlags()


_TECHNICAL_REASON_KEYWORDS: tuple[str, ...] = (
    "MA50", "MA200", "RSI", "momentum", "trend",
    "overheating", "overbought", "oversold",
)

_VALUATION_REASON_KEYWORDS: tuple[str, ...] = (
    "P/E", "valuation", "revenue", "profit margin",
    "debt/equity", "dividend",
)

_RISK_REASON_KEYWORDS: tuple[str, ...] = (
    "volatility", "drawdown", "risk", "earnings",
    "SEC", "8-K", "10-Q", "10-K", "S-1", "DEF 14A",
    "macro event", "catalyst", "market regime",
    "political", "regulatory", "tariff",
)


@dataclass
class ComponentAssessment:
    """A single dimension of the score decomposition.

    score:       numeric value for this dimension (0–100)
    label:       short Russian label — "благоприятный", "умеренный", etc.
    key_reasons: up to 2 deterministic reasons driving this component
    missing:     true when too little data supports this component
    """

    score: float
    label: str
    key_reasons: list[str] = field(default_factory=list)
    missing: bool = False


@dataclass
class ScoreDecomposition:
    """Deterministic, human-readable breakdown of the final score.

    Every component uses a stable label (no buy/sell wording).  The
    decomposition is meant to be rendered alongside (or in place of) the
    raw numeric sub-scores.
    """

    technical: ComponentAssessment
    valuation: ComponentAssessment
    event_risk: ComponentAssessment
    data_confidence: ComponentAssessment
    final_score: float
    final_label: str  # HIGH_INTEREST / WATCH / NEUTRAL / CAUTION / HIGH_RISK


# ---------------------------------------------------------------------------
# Label helpers
# ---------------------------------------------------------------------------

def _technical_label(score: float) -> str:
    if score >= 70:
        return "благоприятный"
    if score >= 50:
        return "смешанный"
    return "слабый"


def _valuation_label(score: float) -> str:
    if score >= 70:
        return "привлекательная"
    if score >= 50:
        return "адекватная"
    return "дороговато"


def _event_risk_label(score: float) -> str:
    if score <= 35:
        return "низкий"
    if score <= 55:
        return "умеренный"
    return "повышенный"


def _data_confidence_label(confidence: float) -> str:
    if confidence >= 0.8:
        return "высокая"
    if confidence >= 0.6:
        return "средняя"
    return "низкая"


# ---------------------------------------------------------------------------
# Reason bucketing
# ---------------------------------------------------------------------------

def _bucket_reasons(reasons: list[str]) -> dict[str, list[str]]:
    """Split a flat reason list into technical / valuation / risk buckets.

    Reasons that don't match any known keyword land in a catch-all "other"
    bucket so nothing is silently dropped.
    """
    buckets: dict[str, list[str]] = {
        "technical": [],
        "valuation": [],
        "risk": [],
        "other": [],
    }
    # Lowercase keywords once for case-insensitive matching
    tech_kw = tuple(kw.lower() for kw in _TECHNICAL_REASON_KEYWORDS)
    val_kw = tuple(kw.lower() for kw in _VALUATION_REASON_KEYWORDS)
    risk_kw = tuple(kw.lower() for kw in _RISK_REASON_KEYWORDS)

    for reason in reasons:
        lower = reason.lower()
        if any(kw in lower for kw in tech_kw):
            buckets["technical"].append(reason)
        elif any(kw in lower for kw in val_kw):
            buckets["valuation"].append(reason)
        elif any(kw in lower for kw in risk_kw):
            buckets["risk"].append(reason)
        else:
            buckets["other"].append(reason)
    return buckets


def _top_reasons(reasons: list[str], max_count: int = 2) -> list[str]:
    """Return up to *max_count* reasons, dropping duplicates."""
    seen: set[str] = set()
    kept: list[str] = []
    for r in reasons:
        norm = r.lower().strip()
        if norm not in seen:
            seen.add(norm)
            kept.append(r)
        if len(kept) >= max_count:
            break
    return kept


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def decompose_scores(
    scores: Scores,
    reasons: list[str],
    data_quality: DataQualityFlags | None = None,
    *,
    final_label: str | None = None,
    _all_reasons: list[str] | None = None,
) -> ScoreDecomposition:
    """Build a deterministic ``ScoreDecomposition`` from scoring output.

    Parameters
    ----------
    scores:
        The four sub-scores (momentum / valuation / risk / final).
    reasons:
        Flat list of reason strings from the scorer.  These are bucketed by
        keyword so the decomposition can show category-specific drivers.
    data_quality:
        Optional quality flags used to derive the data-confidence component.
    final_label:
        Optional override — normally inferred from scores and reasons; pass
        explicitly when already known (e.g. from ``ScoringResult``).
    """
    # Use all reasons for bucketing (if _all_reasons is provided, use the
    # wider set; otherwise fall back to reasons which may already be all).
    all_reasons = _all_reasons if _all_reasons is not None else reasons
    buckets = _bucket_reasons(all_reasons)

    # --- Technical (momentum) ---
    tech_reasons = _top_reasons(
        buckets["technical"] or buckets.get("other", []),
    )
    tech_missing = scores.momentum_score == 50.0 and not buckets["technical"]

    # --- Valuation ---
    val_reasons = _top_reasons(buckets["valuation"])
    val_missing = scores.valuation_score == 55.0 and not buckets["valuation"]

    # --- Event / risk ---
    risk_reasons = _top_reasons(buckets["risk"])
    risk_missing = scores.risk_score == 35.0 and not buckets["risk"]

    # --- Data confidence ---
    dq = _normalize_data_quality(data_quality)
    dq_confidence = dq.confidence
    dq_label = _data_confidence_label(dq_confidence)
    dq_reasons: list[str] = []
    if dq.missing:
        dq_reasons.append("неполные данные")
    if dq.stale:
        dq_reasons.append("устаревшие данные")
    if dq.delayed:
        dq_reasons.append("задержка данных")
    if dq.source_disagreed:
        dq_reasons.append("источники расходятся")

    return ScoreDecomposition(
        technical=ComponentAssessment(
            score=scores.momentum_score,
            label=_technical_label(scores.momentum_score),
            key_reasons=tech_reasons,
            missing=tech_missing,
        ),
        valuation=ComponentAssessment(
            score=scores.valuation_score,
            label=_valuation_label(scores.valuation_score),
            key_reasons=val_reasons,
            missing=val_missing,
        ),
        event_risk=ComponentAssessment(
            score=scores.risk_score,
            label=_event_risk_label(scores.risk_score),
            key_reasons=risk_reasons,
            missing=risk_missing,
        ),
        data_confidence=ComponentAssessment(
            score=round(dq_confidence * 100, 1),
            label=dq_label,
            key_reasons=dq_reasons,
            missing=(dq_confidence <= 0.5),
        ),
        final_score=scores.final_score,
        final_label=final_label or "",
    )


def decomposition_as_payload(decomp: ScoreDecomposition) -> dict[str, Any]:
    """Serialize a ``ScoreDecomposition`` as a plain dict for API payloads."""
    return {
        "technical": {
            "score": decomp.technical.score,
            "label": decomp.technical.label,
            "key_reasons": decomp.technical.key_reasons,
            "missing": decomp.technical.missing,
        },
        "valuation": {
            "score": decomp.valuation.score,
            "label": decomp.valuation.label,
            "key_reasons": decomp.valuation.key_reasons,
            "missing": decomp.valuation.missing,
        },
        "event_risk": {
            "score": decomp.event_risk.score,
            "label": decomp.event_risk.label,
            "key_reasons": decomp.event_risk.key_reasons,
            "missing": decomp.event_risk.missing,
        },
        "data_confidence": {
            "score": decomp.data_confidence.score,
            "label": decomp.data_confidence.label,
            "key_reasons": decomp.data_confidence.key_reasons,
            "missing": decomp.data_confidence.missing,
        },
        "final_score": decomp.final_score,
        "final_label": decomp.final_label,
    }


def format_decomposition_lines(decomp: ScoreDecomposition) -> list[str]:
    """Pretty-print a ``ScoreDecomposition`` for Telegram / CLI output.

    Returns lines ready to be joined with ``\\n``.  No buy/sell wording is
    used — only the stable Russian labels from the plan (HIGH_INTEREST,
    WATCH, NEUTRAL, CAUTION, HIGH_RISK mapped to their Russian equivalents).
    """
    lines: list[str] = []

    # Line 1: final score in conversational form
    from app.services.research_labels import research_label_to_russian

    ru_label = research_label_to_russian(decomp.final_label) if decomp.final_label else ""
    score = decomp.final_score
    if score >= 80:
        emoji = "🟢"
    elif score >= 60:
        emoji = "🔵"
    elif score >= 40:
        emoji = "🟡"
    else:
        emoji = "🔴"

    if decomp.final_label:
        lines.append(f"{emoji} {ru_label} — оценка {score:.0f}")
    else:
        lines.append(f"{emoji} Оценка: {score:.0f}")

    # Compact breakdown
    parts: list[str] = []

    t = decomp.technical
    parts.append(f"📊 тренд {t.label}")

    v = decomp.valuation
    parts.append(f"💰 оценка {v.label}")

    e = decomp.event_risk
    parts.append(f"⚠️ риск {e.label}")

    d = decomp.data_confidence
    parts.append(f"📋 данные {d.label}")

    lines.append(" · ".join(parts))

    # Key reasons — short, grouped
    all_reasons: list[str] = []
    if t.key_reasons:
        all_reasons.extend(t.key_reasons[:2])
    if v.key_reasons:
        all_reasons.extend(v.key_reasons[:1])
    if e.key_reasons:
        all_reasons.extend(e.key_reasons[:1])
    if d.key_reasons:
        all_reasons.extend(d.key_reasons[:1])

    if all_reasons:
        lines.append("")
        for r in all_reasons[:4]:
            lines.append(f"• {r}")

    # Missing data warning
    missing_flags = []
    if t.missing:
        missing_flags.append("технические данные")
    if v.missing:
        missing_flags.append("оценка стоимости")
    if e.missing:
        missing_flags.append("данные о событиях")
    if d.missing:
        missing_flags.append("часть данных")
    if missing_flags:
        lines.append(f"Не хватает: {', '.join(missing_flags)}.")

    return lines
