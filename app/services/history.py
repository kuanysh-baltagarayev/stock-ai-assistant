from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models import AnalysisSnapshot


@dataclass(frozen=True)
class SnapshotAuditEntry:
    snapshot: AnalysisSnapshot
    changes: list[str]


@dataclass
class ScoreDelta:
    """Structured delta between two consecutive analysis snapshots.

    Every field is optional — None means the value was absent in one or
    both snapshots or could not be computed.  The delta is meant to answer
    "why did the score move?" without guessing causal relationships.
    """

    # Price
    price_before: float | None = None
    price_after: float | None = None
    price_change_pct: float | None = None  # signed percentage

    # Final score
    score_before: float | None = None
    score_after: float | None = None
    score_delta: float | None = None  # signed

    # Sub-scores (momentum / valuation / risk)
    sub_score_deltas: dict[str, float] = field(default_factory=dict)

    # Label
    label_before: str | None = None
    label_after: str | None = None

    # Confidence
    confidence_before: float | None = None
    confidence_after: float | None = None

    # Source metadata
    provider_before: str | None = None
    provider_after: str | None = None
    tier_before: str | None = None
    tier_after: str | None = None
    source_url_before: str | None = None
    source_url_after: str | None = None

    # Market session
    session_before: str | None = None
    session_after: str | None = None
    freshness_before: str | None = None
    freshness_after: str | None = None

    # Flag changes
    source_disagreement: bool = False
    new_filings: bool = False
    new_news: bool = False

    # Timestamps
    fetched_at_before: datetime | None = None
    fetched_at_after: datetime | None = None


def list_recent_snapshots(
    db: Session,
    limit: int = 10,
    ticker: str | None = None,
) -> list[AnalysisSnapshot]:
    query = db.query(AnalysisSnapshot)

    if ticker:
        normalized = ticker.strip().upper()
        if normalized:
            query = query.filter(AnalysisSnapshot.ticker == normalized)

    return (
        query.order_by(desc(AnalysisSnapshot.created_at), desc(AnalysisSnapshot.id))
        .limit(limit)
        .all()
    )


def get_snapshot_by_id(db: Session, snapshot_id: int) -> AnalysisSnapshot | None:
    return db.query(AnalysisSnapshot).filter(AnalysisSnapshot.id == snapshot_id).one_or_none()


def build_snapshot_audit_entries(
    snapshots: list[AnalysisSnapshot],
) -> list[SnapshotAuditEntry]:
    entries: list[SnapshotAuditEntry] = []
    for index, snapshot in enumerate(snapshots):
        previous = snapshots[index + 1] if index + 1 < len(snapshots) else None
        entries.append(
            SnapshotAuditEntry(
                snapshot=snapshot,
                changes=_compare_snapshots(snapshot, previous) if previous is not None else [],
            )
        )
    return entries


def build_score_delta(
    current: AnalysisSnapshot,
    previous: AnalysisSnapshot,
) -> ScoreDelta:
    """Compare two snapshots and return a structured ScoreDelta.

    The delta is symmetric — it compares *current* against *previous*
    so ``score_delta > 0`` means the score went up.
    """
    cur_payload = current.payload if isinstance(current.payload, dict) else {}
    prev_payload = previous.payload if isinstance(previous.payload, dict) else {}

    cur_scores = _dict_scores(cur_payload)
    prev_scores = _dict_scores(prev_payload)
    cur_prov = _dict_value(cur_payload, "source_provenance")
    prev_prov = _dict_value(prev_payload, "source_provenance")
    cur_qual = _dict_value(cur_payload, "data_quality")
    prev_qual = _dict_value(prev_payload, "data_quality")
    cur_sess = _dict_value(cur_payload, "market_session")
    prev_sess = _dict_value(prev_payload, "market_session")

    # Price
    price_before = previous.price
    price_after = current.price
    price_change_pct = None
    if price_before is not None and price_after is not None and price_before != 0:
        price_change_pct = ((price_after - price_before) / price_before) * 100

    # Score
    score_before = previous.final_score
    score_after = current.final_score
    score_delta = _safe_sub(score_after, score_before)

    # Sub-score deltas
    sub_deltas: dict[str, float] = {}
    for key in ("momentum_score", "valuation_score", "risk_score"):
        prev_v = prev_scores.get(key)
        cur_v = cur_scores.get(key)
        d = _safe_sub(cur_v, prev_v)
        if d is not None:
            sub_deltas[key] = d

    # Label
    label_before = previous.recommendation if previous.recommendation != current.recommendation else None
    label_after = current.recommendation if label_before is not None else None

    # Confidence
    confidence_before = _dict_float(prev_qual, "confidence")
    confidence_after = _dict_float(cur_qual, "confidence")

    # Source
    provider_before = _dict_str(prev_prov, "provider_name")
    provider_after = _dict_str(cur_prov, "provider_name")
    tier_before = _dict_str(prev_prov, "source_tier")
    tier_after = _dict_str(cur_prov, "source_tier")
    source_url_before = _dict_str(prev_prov, "source_url")
    source_url_after = _dict_str(cur_prov, "source_url")

    # Session
    session_before = _dict_str(prev_sess, "status")
    session_after = _dict_str(cur_sess, "status")
    freshness_before = _dict_str(prev_sess, "freshness_state")
    freshness_after = _dict_str(cur_sess, "freshness_state")

    # Flags
    source_disagreement = _dict_bool(cur_qual, "source_disagreed") or _dict_bool(prev_qual, "source_disagreed")

    # Filings / news — check if sec_filings changed
    new_filings = _has_new_items(_dict_value(cur_payload, "sec_filings"), _dict_value(prev_payload, "sec_filings"))
    new_news = _has_new_items(_dict_value(cur_payload, "news"), _dict_value(prev_payload, "news"))

    # Timestamps
    fetched_at_before = _dict_datetime(prev_prov, "fetched_at")
    fetched_at_after = _dict_datetime(cur_prov, "fetched_at")

    # Only set label changes when they actually differ
    if label_before == label_after:
        label_before = None
        label_after = None

    return ScoreDelta(
        price_before=price_before,
        price_after=price_after,
        price_change_pct=price_change_pct,
        score_before=score_before,
        score_after=score_after,
        score_delta=score_delta,
        sub_score_deltas=sub_deltas,
        label_before=label_before,
        label_after=label_after,
        confidence_before=confidence_before,
        confidence_after=confidence_after,
        provider_before=provider_before,
        provider_after=provider_after,
        tier_before=tier_before,
        tier_after=tier_after,
        source_url_before=source_url_before,
        source_url_after=source_url_after,
        session_before=session_before,
        session_after=session_after,
        freshness_before=freshness_before,
        freshness_after=freshness_after,
        source_disagreement=source_disagreement,
        new_filings=new_filings,
        new_news=new_news,
        fetched_at_before=fetched_at_before,
        fetched_at_after=fetched_at_after,
    )


def probable_drivers(delta: ScoreDelta) -> list[str]:
    """Return a short, deterministic list of what *probably* drove the change.

    This is NOT a causal claim — it lists which fields moved, in priority
    order of impact on the final score.  Every item is directly observable
    from the delta fields.
    """
    drivers: list[str] = []

    # 1. Price movement
    if delta.price_change_pct is not None and abs(delta.price_change_pct) >= 0.5:
        direction = "выросла" if delta.price_change_pct > 0 else "снизилась"
        drivers.append(f"цена {direction} на {abs(delta.price_change_pct):.1f}%")

    # 2. Score movement
    if delta.score_delta is not None and abs(delta.score_delta) >= 0.5:
        direction = "улучшилась" if delta.score_delta > 0 else "ухудшилась"
        drivers.append(f"итоговая оценка {direction} ({delta.score_delta:+.2f})")

    # 3. Sub-score movements
    for key, display in (("momentum_score", "импульс"), ("valuation_score", "оценка стоимости"), ("risk_score", "риск")):
        d = delta.sub_score_deltas.get(key)
        if d is not None and abs(d) >= 1.0:
            direction = "улучшился" if d > 0 else "ухудшился"
            drivers.append(f"{display} {direction} ({d:+.1f})")

    # 4. Label change
    if delta.label_before is not None and delta.label_after is not None:
        drivers.append(f"ярлык изменился: {delta.label_before} → {delta.label_after}")

    # 5. Confidence
    if delta.confidence_before is not None and delta.confidence_after is not None:
        conf_delta = delta.confidence_after - delta.confidence_before
        if abs(conf_delta) >= 0.05:
            direction = "повысилась" if conf_delta > 0 else "снизилась"
            drivers.append(f"уверенность {direction} ({conf_delta:+.2f})")

    # 6. Source change
    if delta.provider_before != delta.provider_after:
        drivers.append(
            f"источник данных изменился: "
            f"{delta.provider_before or 'n/a'} → {delta.provider_after or 'n/a'}"
        )
    if delta.tier_before != delta.tier_after:
        drivers.append(
            f"tier источника: "
            f"{delta.tier_before or 'n/a'} → {delta.tier_after or 'n/a'}"
        )

    # 7. New filings / news
    if delta.new_filings:
        drivers.append("появились новые SEC filings")
    if delta.new_news:
        drivers.append("появились новые новости")

    # 8. Session / freshness
    if delta.session_before != delta.session_after:
        drivers.append(
            f"сессия: {delta.session_before or 'n/a'} → {delta.session_after or 'n/a'}"
        )
    if delta.freshness_before != delta.freshness_after:
        drivers.append(
            f"свежесть: {delta.freshness_before or 'n/a'} → {delta.freshness_after or 'n/a'}"
        )

    return drivers


def format_delta_for_audit(delta: ScoreDelta) -> list[str]:
    """Return formatted lines suitable for /audit Telegram output."""
    lines: list[str] = []

    # Price
    if delta.price_before is not None and delta.price_after is not None:
        pct = f" ({delta.price_change_pct:+.1f}%)" if delta.price_change_pct is not None else ""
        lines.append(f"Цена: {delta.price_before:.2f} → {delta.price_after:.2f}{pct}")

    # Score
    if delta.score_delta is not None:
        lines.append(f"Оценка: {delta.score_before:.2f} → {delta.score_after:.2f} ({delta.score_delta:+.2f})")

    # Sub-scores
    sub_labels = {"momentum_score": "Импульс", "valuation_score": "Стоимость", "risk_score": "Риск"}
    for key, display in sub_labels.items():
        d = delta.sub_score_deltas.get(key)
        if d is not None:
            lines.append(f"  {display}: {d:+.1f}")

    # Label
    if delta.label_before is not None and delta.label_after is not None:
        lines.append(f"Ярлык: {delta.label_before} → {delta.label_after}")

    # Confidence
    if delta.confidence_before is not None and delta.confidence_after is not None:
        cd = delta.confidence_after - delta.confidence_before
        lines.append(f"Уверенность: {delta.confidence_before:.2f} → {delta.confidence_after:.2f} ({cd:+.2f})")

    # Source
    if delta.provider_before != delta.provider_after:
        lines.append(f"Provider: {delta.provider_before or 'n/a'} → {delta.provider_after or 'n/a'}")
    if delta.tier_before != delta.tier_after:
        lines.append(f"Tier: {delta.tier_before or 'n/a'} → {delta.tier_after or 'n/a'}")

    # Session / freshness
    if delta.session_before != delta.session_after:
        lines.append(f"Сессия: {delta.session_before or 'n/a'} → {delta.session_after or 'n/a'}")
    if delta.freshness_before != delta.freshness_after:
        lines.append(f"Свежесть: {delta.freshness_before or 'n/a'} → {delta.freshness_after or 'n/a'}")

    # Source disagreement
    if delta.source_disagreement:
        lines.append("⚠️ Источники расходятся")

    # New items
    if delta.new_filings:
        lines.append("📄 Новые SEC filings")
    if delta.new_news:
        lines.append("📰 Новые новости")

    return lines


def format_delta_for_briefing(delta: ScoreDelta) -> str | None:
    """Return a one-line delta summary for use in daily briefings, or None if
    nothing notable changed."""
    drivers = probable_drivers(delta)
    if not drivers:
        return None
    return " | ".join(drivers[:3])  # Keep briefing compact


def cleanup_old_snapshots(
    db: Session,
    *,
    retention_count: int,
    retention_days: int,
) -> int:
    cutoff = None
    if retention_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_naive = _to_utc_naive(cutoff) if cutoff is not None else None

    snapshots = (
        db.query(AnalysisSnapshot)
        .order_by(
            AnalysisSnapshot.ticker.asc(),
            desc(AnalysisSnapshot.created_at),
            desc(AnalysisSnapshot.id),
        )
        .all()
    )

    keep_ids: set[int] = set()
    per_ticker_counts: dict[str, int] = defaultdict(int)
    for snapshot in snapshots:
        created_at = _to_utc_naive(snapshot.created_at)

        if cutoff_naive is not None and created_at < cutoff_naive:
            continue
        count = per_ticker_counts[snapshot.ticker]
        if count < retention_count:
            keep_ids.add(snapshot.id)
            per_ticker_counts[snapshot.ticker] = count + 1

    purge_ids = [snapshot.id for snapshot in snapshots if snapshot.id not in keep_ids]
    if not purge_ids:
        return 0

    deleted = db.query(AnalysisSnapshot).filter(AnalysisSnapshot.id.in_(purge_ids)).delete(
        synchronize_session=False
    )
    db.commit()
    return deleted


def _to_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


# ── helpers ──────────────────────────────────────────────────────────


def _dict_value(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _dict_scores(payload: dict[str, Any]) -> dict[str, float]:
    """Extract the inner 'scores' dict, or an empty dict."""
    raw = payload.get("scores")
    if isinstance(raw, dict):
        return {k: float(v) for k, v in raw.items() if isinstance(v, (int, float))}
    return {}


def _dict_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value in (None, ""):
        return None
    return str(value)


def _dict_float(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dict_bool(payload: dict[str, Any], key: str) -> bool:
    return bool(payload.get(key))


def _dict_datetime(payload: dict[str, Any], key: str) -> datetime | None:
    value = payload.get(key)
    if isinstance(value, datetime):
        return value
    return None


def _safe_sub(a: float | None, b: float | None) -> float | None:
    if a is not None and b is not None:
        return a - b
    return None


def _has_new_items(
    current: dict[str, Any],
    previous: dict[str, Any],
) -> bool:
    """Detect if new items arrived between two payload dicts.

    Compares by count and by the first item's identifier (filing form_type
    or news title) — not a deep comparison.
    """
    cur_items = _extract_items(current)
    prev_items = _extract_items(previous)
    if not cur_items:
        return False
    if not prev_items:
        # Current has items but previous didn't → genuinely new
        return bool(cur_items)
    # Both have items — check count or first-identifier change
    if len(cur_items) != len(prev_items):
        return True
    # Compare first items' identifiers
    cur_first = cur_items[0]
    prev_first = prev_items[0]
    cid = cur_first.get("form_type") or cur_first.get("title") or ""
    pid = prev_first.get("form_type") or prev_first.get("title") or ""
    return cid != pid


def _extract_items(section: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the item list from a structured section (sec_filings or news)."""
    items = section.get("recent_filings") or section.get("items") or []
    if isinstance(items, list):
        return [i for i in items if isinstance(i, dict)]
    return []


def _compare_snapshots(current: AnalysisSnapshot, previous: AnalysisSnapshot) -> list[str]:
    current_payload = current.payload if isinstance(current.payload, dict) else {}
    previous_payload = previous.payload if isinstance(previous.payload, dict) else {}

    current_provenance = _dict_value(current_payload, "source_provenance")
    previous_provenance = _dict_value(previous_payload, "source_provenance")
    current_quality = _dict_value(current_payload, "data_quality")
    previous_quality = _dict_value(previous_payload, "data_quality")
    current_session = _dict_value(current_payload, "market_session")
    previous_session = _dict_value(previous_payload, "market_session")

    changes: list[str] = []
    _append_numeric_change(changes, "score", previous.final_score, current.final_score)
    _append_numeric_change(changes, "price", previous.price, current.price)
    _append_value_change(changes, "recommendation", previous.recommendation, current.recommendation)
    _append_value_change(
        changes,
        "provider",
        _dict_str(previous_provenance, "provider_name"),
        _dict_str(current_provenance, "provider_name"),
    )
    _append_value_change(
        changes,
        "tier",
        _dict_str(previous_provenance, "source_tier"),
        _dict_str(current_provenance, "source_tier"),
    )
    _append_value_change(
        changes,
        "source_url",
        _dict_str(previous_provenance, "source_url"),
        _dict_str(current_provenance, "source_url"),
    )
    _append_datetime_change(
        changes,
        "fetched_at",
        _dict_datetime(previous_provenance, "fetched_at"),
        _dict_datetime(current_provenance, "fetched_at"),
    )
    _append_numeric_change(
        changes,
        "confidence",
        _dict_float(previous_quality, "confidence"),
        _dict_float(current_quality, "confidence"),
    )
    _append_value_change(
        changes,
        "freshness",
        _dict_str(previous_session, "freshness_state"),
        _dict_str(current_session, "freshness_state"),
    )
    _append_value_change(
        changes,
        "session",
        _dict_str(previous_session, "status"),
        _dict_str(current_session, "status"),
    )

    if _dict_bool(current_quality, "source_disagreed") or _dict_bool(previous_quality, "source_disagreed"):
        changes.append("source disagreement flagged")

    current_note = _dict_str(current_session, "freshness_note")
    previous_note = _dict_str(previous_session, "freshness_note")
    if current_note != previous_note and current_note:
        changes.append(f"freshness note: {current_note}")

    return changes


def _append_numeric_change(
    changes: list[str],
    label: str,
    previous: float | None,
    current: float | None,
) -> None:
    if previous is None or current is None or previous == current:
        return
    delta = current - previous
    changes.append(f"{label}: {previous:.2f} -> {current:.2f} ({delta:+.2f})")


def _append_value_change(
    changes: list[str],
    label: str,
    previous: str | None,
    current: str | None,
) -> None:
    if previous == current:
        return
    if previous is None and current is None:
        return
    changes.append(f"{label}: {previous or 'n/a'} -> {current or 'n/a'}")


def _append_datetime_change(
    changes: list[str],
    label: str,
    previous: datetime | None,
    current: datetime | None,
) -> None:
    if previous == current:
        return
    if previous is None and current is None:
        return
    changes.append(
        f"{label}: {previous.astimezone(timezone.utc).isoformat() if previous else 'n/a'} -> "
        f"{current.astimezone(timezone.utc).isoformat() if current else 'n/a'}"
    )
