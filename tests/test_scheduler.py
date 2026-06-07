"""Tests for scheduler job persistence and degraded digest support."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from app.database import SessionLocal, init_db
from app.models import ScheduledJob, TelegramSubscription


class ScheduledJobModelTest(unittest.TestCase):
    """Test ScheduledJob CRUD and lifecycle."""

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        self._clean()

    def tearDown(self):
        self._clean()
        self.db.close()

    def _clean(self):
        self.db.query(ScheduledJob).delete()
        self.db.commit()

    def _create_job(self, **kwargs) -> ScheduledJob:
        defaults = dict(
            chat_id=12345,
            job_type="digest",
            status="pending",
        )
        defaults.update(kwargs)
        job = ScheduledJob(**defaults)
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def test_create_job(self):
        job = self._create_job()
        self.assertIsNotNone(job.id)
        self.assertEqual(job.chat_id, 12345)
        self.assertEqual(job.job_type, "digest")
        self.assertEqual(job.status, "pending")
        self.assertIsNotNone(job.created_at)

    def test_update_job_status(self):
        job = self._create_job()
        job.status = "running"
        self.db.commit()
        reloaded = self.db.query(ScheduledJob).filter(ScheduledJob.id == job.id).first()
        self.assertEqual(reloaded.status, "running")

    def test_job_failure_reason(self):
        job = self._create_job()
        job.status = "failed"
        job.failure_reason = "no_data"
        self.db.commit()
        reloaded = self.db.query(ScheduledJob).filter(ScheduledJob.id == job.id).first()
        self.assertEqual(reloaded.status, "failed")
        self.assertEqual(reloaded.failure_reason, "no_data")

    def test_multiple_jobs_same_chat_different_types(self):
        job1 = self._create_job(chat_id=111, job_type="digest_market_open")
        job2 = self._create_job(chat_id=111, job_type="alert_check")
        self.assertNotEqual(job1.id, job2.id)

    def test_job_content_fingerprint(self):
        job = self._create_job(content_fingerprint="abc123")
        self.assertEqual(job.content_fingerprint, "abc123")

    def test_job_schedule_cron(self):
        job = self._create_job(schedule_cron="0 9 * * 1-5")
        self.assertEqual(job.schedule_cron, "0 9 * * 1-5")

    def test_job_next_run_at(self):
        now = datetime.now(timezone.utc)
        job = self._create_job(next_run_at=now)
        self.assertIsNotNone(job.next_run_at)

    def test_query_jobs_by_chat(self):
        self._create_job(chat_id=111, job_type="digest")
        self._create_job(chat_id=222, job_type="digest")
        jobs_for_111 = (
            self.db.query(ScheduledJob)
            .filter(ScheduledJob.chat_id == 111)
            .all()
        )
        self.assertEqual(len(jobs_for_111), 1)

    def test_query_jobs_by_type(self):
        self._create_job(job_type="digest")
        self._create_job(job_type="alert_check")
        digests = (
            self.db.query(ScheduledJob)
            .filter(ScheduledJob.job_type == "digest")
            .all()
        )
        self.assertEqual(len(digests), 1)


class TelegramSubscriptionTimezoneTest(unittest.TestCase):
    """Test timezone storage on TelegramSubscription."""

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        self.db.query(TelegramSubscription).delete()
        self.db.commit()

    def tearDown(self):
        self.db.query(TelegramSubscription).delete()
        self.db.commit()
        self.db.close()

    def test_store_timezone(self):
        sub = TelegramSubscription(
            chat_id=111,
            timezone="America/New_York",
            watchlist_symbols=[],
        )
        self.db.add(sub)
        self.db.commit()
        self.db.refresh(sub)
        self.assertEqual(sub.timezone, "America/New_York")

    def test_timezone_defaults_to_none(self):
        sub = TelegramSubscription(
            chat_id=222,
            watchlist_symbols=[],
        )
        self.db.add(sub)
        self.db.commit()
        self.db.refresh(sub)
        self.assertIsNone(sub.timezone)

    def test_upsert_keeps_timezone(self):
        sub = TelegramSubscription(
            chat_id=333,
            timezone="Europe/London",
            watchlist_symbols=[],
        )
        self.db.add(sub)
        self.db.commit()

        sub.timezone = "Asia/Tokyo"
        self.db.commit()
        self.db.refresh(sub)
        self.assertEqual(sub.timezone, "Asia/Tokyo")
