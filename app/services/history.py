from dataclasses import dataclass
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


def _dict_value(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


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
