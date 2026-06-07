"""Tests for usage metrics — product validation counters."""

from __future__ import annotations

import unittest

from app.database import SessionLocal, init_db
from app.models import UsageMetric


class UsageMetricModelTest(unittest.TestCase):
    """Test UsageMetric CRUD and aggregation."""

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        self.db.query(UsageMetric).delete()
        self.db.commit()

    def tearDown(self):
        self.db.query(UsageMetric).delete()
        self.db.commit()
        self.db.close()

    def _create(self, day: str, chat_id: int, command: str, count: int = 1) -> UsageMetric:
        m = UsageMetric(day=day, chat_id=chat_id, command=command, count=count)
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return m

    def test_create_metric(self):
        m = self._create("2026-06-08", 111, "analyze")
        self.assertIsNotNone(m.id)
        self.assertEqual(m.day, "2026-06-08")
        self.assertEqual(m.command, "analyze")
        self.assertEqual(m.count, 1)

    def test_increment_count(self):
        m = self._create("2026-06-08", 111, "scan")
        m.count = m.count + 1
        self.db.commit()
        reloaded = self.db.query(UsageMetric).filter(UsageMetric.id == m.id).first()
        self.assertEqual(reloaded.count, 2)

    def test_multiple_chats_same_command(self):
        self._create("2026-06-08", 111, "scan")
        self._create("2026-06-08", 222, "scan")
        rows = self.db.query(UsageMetric).filter(UsageMetric.command == "scan").all()
        self.assertEqual(len(rows), 2)

    def test_multiple_days(self):
        self._create("2026-06-07", 111, "analyze")
        self._create("2026-06-08", 111, "analyze")
        day7 = self.db.query(UsageMetric).filter(UsageMetric.day == "2026-06-07").all()
        day8 = self.db.query(UsageMetric).filter(UsageMetric.day == "2026-06-08").all()
        self.assertEqual(len(day7), 1)
        self.assertEqual(len(day8), 1)

    def test_active_chats_per_day(self):
        self._create("2026-06-08", 111, "analyze")
        self._create("2026-06-08", 111, "scan")
        self._create("2026-06-08", 222, "analyze")
        rows = self.db.query(UsageMetric).filter(UsageMetric.day == "2026-06-08").all()
        active_chats = len(set(r.chat_id for r in rows))
        self.assertEqual(active_chats, 2)

    def test_command_counts_aggregation(self):
        self._create("2026-06-08", 111, "analyze", 3)
        self._create("2026-06-08", 222, "analyze", 1)
        self._create("2026-06-08", 111, "scan", 2)
        rows = self.db.query(UsageMetric).filter(UsageMetric.day == "2026-06-08").all()
        cmd_totals: dict[str, int] = {}
        for r in rows:
            cmd_totals[r.command] = cmd_totals.get(r.command, 0) + (r.count or 0)
        self.assertEqual(cmd_totals["analyze"], 4)
        self.assertEqual(cmd_totals["scan"], 2)

    def test_no_message_text_stored(self):
        """Verify that UsageMetric has no text/message_content field."""
        m = self._create("2026-06-08", 111, "help")
        # Only day, chat_id, command, count exist
        self.assertFalse(hasattr(m, "message"))
        self.assertFalse(hasattr(m, "text"))
        self.assertFalse(hasattr(m, "content"))
