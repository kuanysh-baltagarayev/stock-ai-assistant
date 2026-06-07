from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AnalysisSnapshot
from app.services.history import (
    build_score_delta,
    cleanup_old_snapshots,
    format_delta_for_audit,
    format_delta_for_briefing,
    probable_drivers,
    ScoreDelta,
)


class HistoryRetentionTests(unittest.TestCase):
    def test_cleanup_old_snapshots_keeps_latest_per_ticker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = create_engine(f"sqlite:///{Path(tmpdir) / 'history.db'}")
            self.addCleanup(engine.dispose)
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
            self.addCleanup(engine.dispose)
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


class ScoreDeltaTests(unittest.TestCase):
    """Tests for build_score_delta, probable_drivers, and formatting."""

    def _make_payload(
        self,
        *,
        momentum_score: float = 50.0,
        valuation_score: float = 50.0,
        risk_score: float = 50.0,
        final_score: float | None = None,
        provider: str = "yfinance",
        tier: str = "tier 2",
        source_url: str = "https://example.com",
        confidence: float = 0.80,
        session: str = "market_open",
        freshness: str = "fresh",
        source_disagreed: bool = False,
        sec_filings: list[dict] | None = None,
        news: list[dict] | None = None,
        fetched_at: datetime | None = None,
    ) -> dict:
        payload: dict = {
            "scores": {
                "momentum_score": momentum_score,
                "valuation_score": valuation_score,
                "risk_score": risk_score,
            },
            "source_provenance": {
                "provider_name": provider,
                "source_tier": tier,
                "source_url": source_url,
            },
            "data_quality": {
                "confidence": confidence,
                "source_disagreed": source_disagreed,
            },
            "market_session": {
                "status": session,
                "freshness_state": freshness,
            },
        }
        if final_score is not None:
            payload["scores"]["final_score"] = final_score
        if fetched_at is not None:
            payload["source_provenance"]["fetched_at"] = fetched_at
        if sec_filings is not None:
            payload["sec_filings"] = {"recent_filings": sec_filings}
        if news is not None:
            payload["news"] = {"items": news}
        return payload

    def _make_snapshot(
        self,
        payload: dict,
        *,
        ticker: str = "AAPL",
        final_score: float = 50.0,
        price: float = 100.0,
        recommendation: str = "NEUTRAL",
        created_at: datetime | None = None,
    ) -> AnalysisSnapshot:
        return AnalysisSnapshot(
            ticker=ticker,
            company_name="Apple Inc.",
            price=price,
            final_score=final_score,
            recommendation=recommendation,
            payload=payload,
            created_at=created_at or datetime.now(timezone.utc),
        )

    # ── build_score_delta tests ──────────────────────────────────────

    def test_build_score_delta_basic(self) -> None:
        """ScoreDelta captures price, score, label, confidence, source, session changes."""
        now = datetime.now(timezone.utc)
        prev = self._make_snapshot(
            self._make_payload(confidence=0.81, session="open", freshness="fresh"),
            final_score=54.2, price=189.12, recommendation="WATCH",
            created_at=now - timedelta(hours=2),
        )
        cur = self._make_snapshot(
            self._make_payload(
                momentum_score=55.0, valuation_score=60.0, risk_score=45.0,
                provider="alpha_vantage", tier="tier 1", confidence=0.75,
                session="after_hours", freshness="session_closed",
                source_disagreed=True,
            ),
            final_score=62.5, price=192.50, recommendation="NEUTRAL",
            created_at=now,
        )

        delta = build_score_delta(cur, prev)

        # Price
        self.assertAlmostEqual(delta.price_before, 189.12)
        self.assertAlmostEqual(delta.price_after, 192.50)
        self.assertIsNotNone(delta.price_change_pct)
        self.assertAlmostEqual(delta.price_change_pct, 1.79, places=1)  # (192.5-189.12)/189.12*100

        # Score
        self.assertAlmostEqual(delta.score_before, 54.2)
        self.assertAlmostEqual(delta.score_after, 62.5)
        self.assertAlmostEqual(delta.score_delta, 8.3)

        # Sub-scores
        self.assertIn("momentum_score", delta.sub_score_deltas)
        self.assertAlmostEqual(delta.sub_score_deltas["momentum_score"], 5.0)
        self.assertIn("valuation_score", delta.sub_score_deltas)
        self.assertAlmostEqual(delta.sub_score_deltas["valuation_score"], 10.0)
        self.assertIn("risk_score", delta.sub_score_deltas)
        self.assertAlmostEqual(delta.sub_score_deltas["risk_score"], -5.0)

        # Label
        self.assertEqual(delta.label_before, "WATCH")
        self.assertEqual(delta.label_after, "NEUTRAL")

        # Confidence
        self.assertAlmostEqual(delta.confidence_before, 0.81)
        self.assertAlmostEqual(delta.confidence_after, 0.75)

        # Source
        self.assertEqual(delta.provider_before, "yfinance")
        self.assertEqual(delta.provider_after, "alpha_vantage")
        self.assertEqual(delta.tier_before, "tier 2")
        self.assertEqual(delta.tier_after, "tier 1")

        # Session
        self.assertEqual(delta.session_before, "open")
        self.assertEqual(delta.session_after, "after_hours")
        self.assertEqual(delta.freshness_before, "fresh")
        self.assertEqual(delta.freshness_after, "session_closed")

        # Flags
        self.assertTrue(delta.source_disagreement)

    def test_build_score_delta_no_changes(self) -> None:
        """When nothing changed, ScoreDelta has empty diffs."""
        now = datetime.now(timezone.utc)
        payload = self._make_payload()
        prev = self._make_snapshot(payload, created_at=now - timedelta(hours=1))
        cur = self._make_snapshot(payload, created_at=now)

        delta = build_score_delta(cur, prev)

        self.assertEqual(delta.score_delta, 0.0)
        self.assertEqual(delta.price_change_pct, 0.0)
        self.assertIsNone(delta.label_before)
        self.assertIsNone(delta.label_after)
        self.assertAlmostEqual(delta.confidence_before, 0.80)
        self.assertAlmostEqual(delta.confidence_after, 0.80)
        self.assertEqual(delta.provider_before, delta.provider_after)
        self.assertFalse(delta.source_disagreement)
        self.assertFalse(delta.new_filings)
        self.assertFalse(delta.new_news)

    def test_build_score_delta_missing_payload(self) -> None:
        """Empty/missing payload should not crash."""
        now = datetime.now(timezone.utc)
        prev = AnalysisSnapshot(
            ticker="AAPL", company_name="Apple Inc.",
            price=None, final_score=50.0, recommendation="NEUTRAL",
            payload={}, created_at=now - timedelta(hours=1),
        )
        cur = AnalysisSnapshot(
            ticker="AAPL", company_name="Apple Inc.",
            price=None, final_score=55.0, recommendation="NEUTRAL",
            payload={}, created_at=now,
        )

        delta = build_score_delta(cur, prev)

        self.assertIsNone(delta.price_before)
        self.assertIsNone(delta.price_after)
        self.assertIsNone(delta.price_change_pct)
        self.assertAlmostEqual(delta.score_delta, 5.0)
        self.assertEqual(delta.sub_score_deltas, {})
        self.assertIsNone(delta.confidence_before)
        self.assertIsNone(delta.confidence_after)
        self.assertFalse(delta.source_disagreement)

    def test_build_score_delta_new_filings_and_news(self) -> None:
        """Detects new SEC filings and news items."""
        now = datetime.now(timezone.utc)
        prev = self._make_snapshot(
            self._make_payload(sec_filings=None, news=[]),
            created_at=now - timedelta(hours=1),
        )
        cur = self._make_snapshot(
            self._make_payload(
                sec_filings=[{"form_type": "8-K", "description": "New filing"}],
                news=[{"title": "Quarterly results beat expectations"}],
            ),
            created_at=now,
        )

        delta = build_score_delta(cur, prev)

        self.assertTrue(delta.new_filings)
        self.assertTrue(delta.new_news)

    def test_build_score_delta_source_url_change(self) -> None:
        """Changing source URL is captured."""
        now = datetime.now(timezone.utc)
        prev = self._make_snapshot(
            self._make_payload(source_url="https://old.example.com"),
            created_at=now - timedelta(hours=1),
        )
        cur = self._make_snapshot(
            self._make_payload(source_url="https://new.example.com"),
            created_at=now,
        )

        delta = build_score_delta(cur, prev)

        self.assertEqual(delta.source_url_before, "https://old.example.com")
        self.assertEqual(delta.source_url_after, "https://new.example.com")

    def test_build_score_delta_fetched_at_change(self) -> None:
        """Changing fetched_at is captured."""
        now = datetime.now(timezone.utc)
        prev = self._make_snapshot(
            self._make_payload(fetched_at=now - timedelta(hours=2)),
            created_at=now - timedelta(hours=1),
        )
        cur = self._make_snapshot(
            self._make_payload(fetched_at=now),
            created_at=now,
        )

        delta = build_score_delta(cur, prev)

        self.assertIsNotNone(delta.fetched_at_before)
        self.assertIsNotNone(delta.fetched_at_after)

    # ── probable_drivers tests ───────────────────────────────────────

    def test_probable_drivers_score_delta(self) -> None:
        """Large score delta produces driver."""
        delta = ScoreDelta(score_before=50.0, score_after=62.5, score_delta=12.5)
        drivers = probable_drivers(delta)
        self.assertTrue(any("улучшилась" in d and "12.50" in d for d in drivers))

    def test_probable_drivers_score_delta_small(self) -> None:
        """Small score delta (<0.5) is skipped."""
        delta = ScoreDelta(score_before=50.0, score_after=50.3, score_delta=0.3)
        drivers = probable_drivers(delta)
        self.assertFalse(any("оценка" in d for d in drivers))

    def test_probable_drivers_price_delta(self) -> None:
        """Price change >=0.5% produces driver."""
        delta = ScoreDelta(price_before=100.0, price_after=105.0, price_change_pct=5.0)
        drivers = probable_drivers(delta)
        self.assertTrue(any("выросла" in d and "5.0%" in d for d in drivers))

    def test_probable_drivers_label_change(self) -> None:
        """Label change produces driver."""
        delta = ScoreDelta(label_before="WATCH", label_after="NEUTRAL")
        drivers = probable_drivers(delta)
        self.assertTrue(any("ярлык" in d and "WATCH" in d and "NEUTRAL" in d for d in drivers))

    def test_probable_drivers_confidence_down(self) -> None:
        """Confidence decrease >=0.05 produces driver."""
        delta = ScoreDelta(confidence_before=0.80, confidence_after=0.70)
        drivers = probable_drivers(delta)
        self.assertTrue(any("снизилась" in d for d in drivers))

    def test_probable_drivers_confidence_small_change(self) -> None:
        """Confidence change <0.05 is skipped."""
        delta = ScoreDelta(confidence_before=0.80, confidence_after=0.78)
        drivers = probable_drivers(delta)
        self.assertFalse(any("уверенность" in d for d in drivers))

    def test_probable_drivers_provider_change(self) -> None:
        """Provider change produces driver."""
        delta = ScoreDelta(provider_before="yfinance", provider_after="alpha_vantage")
        drivers = probable_drivers(delta)
        self.assertTrue(any("источник" in d and "yfinance" in d and "alpha_vantage" in d for d in drivers))

    def test_probable_drivers_tier_change(self) -> None:
        """Tier change produces driver."""
        delta = ScoreDelta(tier_before="tier 2", tier_after="tier 1")
        drivers = probable_drivers(delta)
        self.assertTrue(any("tier" in d and "tier 2" in d and "tier 1" in d for d in drivers))

    def test_probable_drivers_new_filings(self) -> None:
        """New filings produce driver."""
        delta = ScoreDelta(new_filings=True)
        drivers = probable_drivers(delta)
        self.assertTrue(any("sec filings" in d.lower() for d in drivers))

    def test_probable_drivers_new_news(self) -> None:
        """New news produce driver."""
        delta = ScoreDelta(new_news=True)
        drivers = probable_drivers(delta)
        self.assertTrue(any("новости" in d for d in drivers))

    def test_probable_drivers_session_change(self) -> None:
        """Session change produces driver."""
        delta = ScoreDelta(session_before="open", session_after="after_hours")
        drivers = probable_drivers(delta)
        self.assertTrue(any("сессия" in d and "open" in d for d in drivers))

    def test_probable_drivers_freshness_change(self) -> None:
        """Freshness change produces driver."""
        delta = ScoreDelta(freshness_before="fresh", freshness_after="stale")
        drivers = probable_drivers(delta)
        self.assertTrue(any("свежесть" in d for d in drivers))

    def test_probable_drivers_no_changes(self) -> None:
        """No changes → empty drivers list."""
        delta = ScoreDelta(score_before=50.0, score_after=50.0, score_delta=0.0)
        drivers = probable_drivers(delta)
        self.assertEqual(drivers, [])

    def test_probable_drivers_sub_score_momentum(self) -> None:
        """Sub-score delta >=1.0 produces driver."""
        delta = ScoreDelta(sub_score_deltas={"momentum_score": 3.5})
        drivers = probable_drivers(delta)
        self.assertTrue(any("импульс" in d and "3.5" in d for d in drivers))

    def test_probable_drivers_sub_score_valuation(self) -> None:
        """Valuation sub-score delta produces driver."""
        delta = ScoreDelta(sub_score_deltas={"valuation_score": -2.0})
        drivers = probable_drivers(delta)
        self.assertTrue(any("стоимости" in d for d in drivers))

    def test_probable_drivers_sub_score_small(self) -> None:
        """Small sub-score delta (<1.0) is skipped."""
        delta = ScoreDelta(sub_score_deltas={"momentum_score": 0.5})
        drivers = probable_drivers(delta)
        self.assertFalse(any("импульс" in d for d in drivers))

    def test_probable_drivers_complex(self) -> None:
        """Multiple changes produce multiple drivers in priority order."""
        delta = ScoreDelta(
            price_before=100.0, price_after=95.0, price_change_pct=-5.0,
            score_before=60.0, score_after=50.0, score_delta=-10.0,
            sub_score_deltas={"momentum_score": -8.0, "risk_score": 7.0},
            label_before="WATCH", label_after="CAUTION",
            confidence_before=0.85, confidence_after=0.60,
            provider_before="yfinance", provider_after="unknown_provider",
            source_disagreement=True,
            new_filings=True,
            session_before="market_open", session_after="closed",
        )
        drivers = probable_drivers(delta)
        # At least 5 drivers expected
        self.assertGreaterEqual(len(drivers), 5)
        # Price change comes first (most impactful)
        self.assertIn("снизилась", drivers[0])

    # ── format_delta_for_audit tests ─────────────────────────────────

    def test_format_delta_for_audit_basic(self) -> None:
        """Format produces lines for all changed fields."""
        delta = ScoreDelta(
            price_before=100.0, price_after=105.0, price_change_pct=5.0,
            score_before=50.0, score_after=55.0, score_delta=5.0,
            sub_score_deltas={"momentum_score": 3.0, "valuation_score": -1.0},
            label_before="NEUTRAL", label_after="WATCH",
            confidence_before=0.80, confidence_after=0.85,
            provider_before="yfinance", provider_after="alpha_vantage",
            source_disagreement=True,
        )
        lines = format_delta_for_audit(delta)

        full = "\n".join(lines).lower()
        self.assertIn("цена", full)
        self.assertIn("оценка", full)
        self.assertIn("импульс", full)
        self.assertIn("стоимость", full)
        self.assertIn("ярлык", full)
        self.assertIn("уверенность", full)
        self.assertIn("provider", full)
        self.assertIn("источники расходятся", full)

    def test_format_delta_for_audit_empty(self) -> None:
        """Empty delta produces minimal output."""
        lines = format_delta_for_audit(ScoreDelta())
        self.assertEqual(lines, [])

    def test_format_delta_for_audit_new_items(self) -> None:
        """Format includes new filings/news markers."""
        delta = ScoreDelta(new_filings=True, new_news=True)
        lines = format_delta_for_audit(delta)
        full = "\n".join(lines)
        self.assertIn("SEC filings", full)
        self.assertIn("📰", full)

    # ── format_delta_for_briefing tests ───────────────────────────────

    def test_format_delta_for_briefing_notable(self) -> None:
        """Notable changes produce a compact string."""
        delta = ScoreDelta(
            score_before=50.0, score_after=55.0, score_delta=5.0,
            label_before="NEUTRAL", label_after="WATCH",
        )
        result = format_delta_for_briefing(delta)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)
        self.assertIn("улучшилась", result)

    def test_format_delta_for_briefing_no_change(self) -> None:
        """No notable changes produce None."""
        delta = ScoreDelta(score_before=50.0, score_after=50.05, score_delta=0.05)
        result = format_delta_for_briefing(delta)
        self.assertIsNone(result)

    def test_format_delta_for_briefing_truncated(self) -> None:
        """Long delta is truncated to 3 drivers."""
        delta = ScoreDelta(
            price_before=100.0, price_after=95.0, price_change_pct=-5.0,
            score_before=60.0, score_after=40.0, score_delta=-20.0,
            sub_score_deltas={"momentum_score": -10.0, "valuation_score": -5.0, "risk_score": 8.0},
            label_before="NEUTRAL", label_after="CAUTION",
            confidence_before=0.85, confidence_after=0.55,
            provider_before="yfinance", provider_after="unknown",
        )
        result = format_delta_for_briefing(delta)
        self.assertIsNotNone(result)
        # At most 3 pipe-separated items
        self.assertLessEqual(result.count("|"), 2)


if __name__ == "__main__":
    unittest.main()
