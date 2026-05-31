from __future__ import annotations

from datetime import datetime, timezone
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.services.runtime_budget import reset_runtime_budgets
from app.services.telegram_bot import TelegramBotService


class TelegramDigestModeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_runtime_budgets()
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "digests.db"
        self.engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(bind=self.engine)
        self.session_factory = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.session_patcher = patch("app.services.telegram_bot.SessionLocal", self.session_factory)
        self.session_patcher.start()
        self.service = TelegramBotService(
            settings=SimpleNamespace(
                telegram_enabled=True,
                telegram_bot_token="123456:abcdefghijklmnopqrstuvwxyzABCDEF",
                telegram_default_tickers="AAPL,MSFT,NVDA",
                telegram_allowed_chat_ids=[],
                telegram_digest_interval_minutes=1440,
                telegram_poll_timeout_seconds=1,
                telegram_send_budget=100,
            )
        )
        self.service._upsert_subscription(1001, username="alice", active=True, watchlist_symbols=["AAPL"])

    def tearDown(self) -> None:
        reset_runtime_budgets()
        self.session_patcher.stop()
        self.engine.dispose()
        self._tmpdir.cleanup()

    def test_scheduled_digest_mode_changes_by_session_time(self) -> None:
        cases = [
            (datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc), "pre_market"),
            (datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc), "market_open"),
            (datetime(2026, 6, 1, 17, 30, tzinfo=timezone.utc), "midday"),
            (datetime(2026, 6, 1, 20, 30, tzinfo=timezone.utc), "close"),
            (datetime(2026, 6, 1, 22, 30, tzinfo=timezone.utc), "after_hours"),
            (datetime(2026, 6, 7, 16, 0, tzinfo=timezone.utc), "weekly_review"),
        ]

        for reference_time, expected_mode in cases:
            with self.subTest(reference_time=reference_time, expected_mode=expected_mode):
                self.assertEqual(self.service._scheduled_digest_mode(reference_time), expected_mode)

    async def test_scheduled_digest_uses_mode_specific_heading(self) -> None:
        fake_scan = SimpleNamespace(
            results=[
                SimpleNamespace(
                    ticker="AAPL",
                    recommendation="NEUTRAL",
                    final_score=61.0,
                    price=189.12,
                    short_reason="sample reason",
                )
            ],
            errors=[],
            summary=SimpleNamespace(partial_failure=False, message="ok", failed_tickers=[]),
        )
        send_mock = AsyncMock()

        with (
            patch("app.services.telegram_bot.scan_tickers", return_value=fake_scan),
            patch.object(self.service, "_send_message", send_mock),
            patch.object(self.service, "_scheduled_digest_mode", return_value="close"),
        ):
            await self.service._send_digest_to_active_subscribers()

        self.assertEqual(send_mock.await_count, 1)
        self.assertIn("Close summary дайджест", send_mock.await_args.args[1])
