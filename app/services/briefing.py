from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BriefingItem:
    ticker: str
    label: str
    final_score: float
    price: float | None
    short_reason: str
    group: str
    confidence: float | None = None
    risk_score: float | None = None
    source_provider: str | None = None
    source_tier: str | None = None
    market_session_status: str | None = None
    freshness_state: str | None = None
    flags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BriefingSummary:
    items: tuple[BriefingItem, ...]
    hidden_low_confidence_count: int = 0
    error_count: int = 0
    degraded_count: int = 0

    @property
    def key_items(self) -> tuple[BriefingItem, ...]:
        return tuple(item for item in self.items if item.group == "key")

    @property
    def watch_items(self) -> tuple[BriefingItem, ...]:
        return tuple(item for item in self.items if item.group == "watch")

    @property
    def risk_items(self) -> tuple[BriefingItem, ...]:
        return tuple(item for item in self.items if item.group == "risk")


def build_scan_briefing(
    results: list[Any],
    errors: list[Any] | None = None,
    *,
    min_confidence: float | None = None,
    limit: int = 5,
) -> BriefingSummary:
    """Build a deterministic scan briefing for Telegram and CLI views."""
    considered = list(results[:limit])
    visible: list[Any] = []
    hidden_low_confidence_count = 0

    for item in considered:
        confidence = _confidence(item)
        if min_confidence is not None:
            if confidence is None or confidence < min_confidence:
                hidden_low_confidence_count += 1
                continue
        visible.append(item)

    briefing_items = tuple(_briefing_item(item) for item in visible)
    degraded_count = sum(1 for item in briefing_items if item.flags)
    return BriefingSummary(
        items=briefing_items,
        hidden_low_confidence_count=hidden_low_confidence_count,
        error_count=len(errors or []),
        degraded_count=degraded_count,
    )


def _briefing_item(item: Any) -> BriefingItem:
    recommendation = str(getattr(item, "recommendation", "") or "NEUTRAL")
    risk_score = _float_or_none(getattr(item, "risk_score", None))
    confidence = _confidence(item)
    flags = _quality_flags(item, confidence=confidence, risk_score=risk_score)
    return BriefingItem(
        ticker=str(getattr(item, "ticker", "") or "").upper(),
        label=recommendation,
        final_score=float(getattr(item, "final_score", 0.0) or 0.0),
        price=_float_or_none(getattr(item, "price", None)),
        short_reason=str(getattr(item, "short_reason", "") or ""),
        group=_briefing_group(recommendation, risk_score=risk_score),
        confidence=confidence,
        risk_score=risk_score,
        source_provider=_str_or_none(getattr(item, "source_provider", None)),
        source_tier=_str_or_none(getattr(item, "source_tier", None)),
        market_session_status=_str_or_none(getattr(item, "market_session_status", None)),
        freshness_state=_str_or_none(getattr(item, "freshness_state", None)),
        flags=flags,
    )


def _briefing_group(recommendation: str, *, risk_score: float | None) -> str:
    if recommendation in {"HIGH_RISK", "CAUTION"}:
        return "risk"
    if risk_score is not None and risk_score >= 70:
        return "risk"
    if recommendation in {"HIGH_INTEREST", "WATCH"}:
        return "key"
    return "watch"


def _quality_flags(
    item: Any,
    *,
    confidence: float | None,
    risk_score: float | None,
) -> tuple[str, ...]:
    flags: list[str] = []
    if confidence is None:
        flags.append("confidence n/a")
    elif confidence < 0.6:
        flags.append(f"low confidence {confidence:.2f}")
    elif confidence < 0.8:
        flags.append(f"medium confidence {confidence:.2f}")

    if risk_score is not None and risk_score >= 70:
        flags.append(f"high risk {risk_score:.0f}")

    quality = getattr(item, "data_quality", None)
    for attr, label in (
        ("stale", "stale data"),
        ("delayed", "delayed data"),
        ("missing", "missing data"),
        ("source_disagreed", "source disagreement"),
    ):
        if _truthy_quality_flag(quality, attr) or bool(getattr(item, attr, False)):
            flags.append(label)

    freshness_state = getattr(item, "freshness_state", None)
    if isinstance(freshness_state, str) and freshness_state in {"stale", "delayed"}:
        flags.append(f"{freshness_state} signal")

    if not getattr(item, "source_provider", None):
        flags.append("source provider n/a")
    if not getattr(item, "market_session_status", None):
        flags.append("session n/a")

    return tuple(dict.fromkeys(flags))


def _truthy_quality_flag(quality: Any, attr: str) -> bool:
    if quality is None:
        return False
    if isinstance(quality, dict):
        return bool(quality.get(attr))
    return bool(getattr(quality, attr, False))


def _confidence(item: Any) -> float | None:
    confidence = _float_or_none(getattr(item, "confidence", None))
    if confidence is not None:
        return confidence
    quality = getattr(item, "data_quality", None)
    if isinstance(quality, dict):
        return _float_or_none(quality.get("confidence"))
    return _float_or_none(getattr(quality, "confidence", None))


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
