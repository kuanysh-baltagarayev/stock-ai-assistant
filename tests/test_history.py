from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AnalysisSnapshot
from app.services.history import cleanup_old_snapshots


class HistoryRetentionTests(unittest.TestCase):
    def test_cleanup_old_snapshots_keeps_latest_per_ticker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = create_engine(f"sqlite:///{Path(tmpdir) / 'history.db'}")
            Base.metadata.create_all(bind=engine)
            Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

            now = datetime.now(timezone.utc)
            with Session() as db:
                db.add_all(
                    [
                        AnalysisSnapshot(
                            ticker="AAPL",
                            company_name="Apple Inc.",
                            price=100.0,
                            final_score=80.0,
                            recommendation="NEUTRAL",
                            payload={"ticker": "AAPL"},
                            created_at=now,
                        ),
                        AnalysisSnapshot(
                            ticker="AAPL",
                            company_name="Apple Inc.",
                            price=99.0,
                            final_score=79.0,
                            recommendation="NEUTRAL",
                            payload={"ticker": "AAPL"},
                            created_at=now - timedelta(days=1),
                        ),
                        AnalysisSnapshot(
                            ticker="AAPL",
                            company_name="Apple Inc.",
                            price=98.0,
                            final_score=78.0,
                            recommendation="NEUTRAL",
                            payload={"ticker": "AAPL"},
                            created_at=now - timedelta(days=2),
                        ),
                        AnalysisSnapshot(
                            ticker="MSFT",
                            company_name="Microsoft Corp.",
                            price=200.0,
                            final_score=81.0,
                            recommendation="NEUTRAL",
                            payload={"ticker": "MSFT"},
                            created_at=now,
                        ),
                    ]
                )
                db.commit()

                deleted = cleanup_old_snapshots(
                    db,
                    retention_count=2,
                    retention_days=0,
                )

                remaining = db.query(AnalysisSnapshot).order_by(AnalysisSnapshot.ticker, AnalysisSnapshot.created_at.desc()).all()

            self.assertEqual(deleted, 1)
            self.assertEqual(
                [(snapshot.ticker, snapshot.price) for snapshot in remaining],
                [("AAPL", 100.0), ("AAPL", 99.0), ("MSFT", 200.0)],
            )

    def test_cleanup_old_snapshots_removes_aged_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = create_engine(f"sqlite:///{Path(tmpdir) / 'history.db'}")
            Base.metadata.create_all(bind=engine)
            Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

            now = datetime.now(timezone.utc)
            with Session() as db:
                db.add_all(
                    [
                        AnalysisSnapshot(
                            ticker="AAPL",
                            company_name="Apple Inc.",
                            price=100.0,
                            final_score=80.0,
                            recommendation="NEUTRAL",
                            payload={"ticker": "AAPL"},
                            created_at=now - timedelta(days=10),
                        ),
                        AnalysisSnapshot(
                            ticker="AAPL",
                            company_name="Apple Inc.",
                            price=101.0,
                            final_score=81.0,
                            recommendation="NEUTRAL",
                            payload={"ticker": "AAPL"},
                            created_at=now,
                        ),
                    ]
                )
                db.commit()

                deleted = cleanup_old_snapshots(
                    db,
                    retention_count=10,
                    retention_days=1,
                )

                remaining = db.query(AnalysisSnapshot).all()

            self.assertEqual(deleted, 1)
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0].price, 101.0)
