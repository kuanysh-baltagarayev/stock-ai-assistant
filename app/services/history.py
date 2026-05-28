from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models import AnalysisSnapshot


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
