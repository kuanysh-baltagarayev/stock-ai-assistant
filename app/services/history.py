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
