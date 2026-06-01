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


class TelegramPreferenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_runtime_budgets()
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "preferences.db"
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

    def tearDown(self) -> None:
        reset_runtime_budgets()
        self.session_patcher.stop()
        self.engine.dispose()
        self._tmpdir.cleanup()

    async def test_preference_commands_update_subscription(self) -> None:
        send_mock = AsyncMock()

        with patch.object(self.service, "_send_message", send_mock):
            await self.service._handle_update(
                {
                    "message": {
                        "chat": {"id": 101},
                        "from": {"username": "alice"},
                        "text": "/quiet 22:00-07:00",
                    }
                }
            )
            await self.service._handle_update(
                {
                    "message": {
                        "chat": {"id": 101},
                        "from": {"username": "alice"},
                        "text": "/cap 2",
                    }
                }
            )
            await self.service._handle_update(
                {
                    "message": {
                        "chat": {"id": 101},
                        "from": {"username": "alice"},
                        "text": "/markethours on",
                    }
                }
            )
            await self.service._handle_update(
                {
                    "message": {
                        "chat": {"id": 101},
                        "from": {"username": "alice"},
                        "text": "/confidence 0.75",
                    }
                }
            )
            await self.service._handle_update(
                {
                    "message": {
                        "chat": {"id": 101},
                        "from": {"username": "alice"},
                        "text": "/prefs",
                    }
                }
            )
            await self.service._handle_update(
                {
                    "message": {
                        "chat": {"id": 101},
                        "from": {"username": "alice"},
                        "text": "/status",
                    }
                }
            )

        subscription = self.service._subscription_for_chat(101)
        self.assertIsNotNone(subscription)
        self.assertEqual(subscription.quiet_hours_start_minute, 22 * 60)
        self.assertEqual(subscription.quiet_hours_end_minute, 7 * 60)
        self.assertEqual(subscription.max_alerts_per_day, 2)
        self.assertTrue(subscription.market_hours_only)
        self.assertEqual(subscription.min_confidence, 0.75)
        self.assertEqual(send_mock.await_count, 6)
        self.assertIn("Настройки уведомлений", send_mock.await_args_list[-2].args[1])
        self.assertIn("Минимальная уверенность: 0.75", send_mock.await_args_list[-2].args[1])
        self.assertIn("Порог уверенности: 0.75", send_mock.await_args_list[-1].args[1])

    async def test_unsubscribe_clears_personal_data(self) -> None:
        self.service._upsert_subscription(
            505,
            username="erin",
            active=True,
            watchlist_symbols=["AAPL", "NVDA"],
            preferences={
                "quiet_hours_start_minute": 22 * 60,
                "quiet_hours_end_minute": 7 * 60,
                "max_alerts_per_day": 2,
                "market_hours_only": True,
                "daily_alert_count": 3,
                "daily_alert_date": "2026-06-01",
                "last_alert_at": datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc),
            },
        )
        send_mock = AsyncMock()

        with patch.object(self.service, "_send_message", send_mock):
            await self.service._handle_update(
                {
                    "message": {
                        "chat": {"id": 505},
                        "from": {"username": "erin"},
                        "text": "/unsubscribe",
                    }
                }
            )

        subscription = self.service._subscription_for_chat(505)
        self.assertIsNotNone(subscription)
        self.assertFalse(subscription.is_active)
        self.assertEqual(subscription.watchlist_symbols, [])
        self.assertIsNone(subscription.quiet_hours_start_minute)
        self.assertIsNone(subscription.quiet_hours_end_minute)
        self.assertIsNone(subscription.max_alerts_per_day)
        self.assertFalse(subscription.market_hours_only)
        self.assertEqual(subscription.daily_alert_count, 0)
        self.assertIsNone(subscription.daily_alert_date)
        self.assertIsNone(subscription.last_alert_at)
        self.assertIsNone(subscription.last_digest_fingerprint)
        self.assertIn("данные списка и уведомлений очищены", send_mock.await_args.args[1])

    async def test_digest_skips_market_hours_only_subscribers_when_market_closed(self) -> None:
        self.service._upsert_subscription(
            202,
            username="bob",
            active=True,
            watchlist_symbols=["AAPL"],
            preferences={"market_hours_only": True},
        )
        send_mock = AsyncMock()
        fake_scan = SimpleNamespace(
            results=[],
            errors=[],
            summary=SimpleNamespace(partial_failure=False, message="ok", failed_tickers=[]),
        )

        with (
            patch.object(self.service, "_is_market_session_open", return_value=False),
            patch.object(self.service, "_send_message", send_mock),
            patch("app.services.telegram_bot.scan_tickers", return_value=fake_scan) as scan_mock,
        ):
            await self.service._send_digest_to_active_subscribers()

        scan_mock.assert_not_called()
        send_mock.assert_not_called()

    async def test_digest_skips_subscribers_after_daily_cap_is_reached(self) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        self.service._upsert_subscription(
            303,
            username="carol",
            active=True,
            watchlist_symbols=["MSFT"],
            preferences={
                "max_alerts_per_day": 1,
                "daily_alert_count": 1,
                "daily_alert_date": today,
            },
        )
        send_mock = AsyncMock()
        fake_scan = SimpleNamespace(
            results=[],
            errors=[],
            summary=SimpleNamespace(partial_failure=False, message="ok", failed_tickers=[]),
        )

        with (
            patch.object(self.service, "_quiet_hours_active", return_value=False),
            patch.object(self.service, "_is_market_session_open", return_value=True),
            patch.object(self.service, "_send_message", send_mock),
            patch("app.services.telegram_bot.scan_tickers", return_value=fake_scan) as scan_mock,
        ):
            await self.service._send_digest_to_active_subscribers()

        scan_mock.assert_not_called()
        send_mock.assert_not_called()

    def test_mark_last_alert_tracks_daily_count(self) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        self.service._upsert_subscription(404, username="dave", active=True, watchlist_symbols=["NVDA"])

        self.service._mark_last_alert(self.service._subscription_for_chat(404).id)

        subscription = self.service._subscription_for_chat(404)
        self.assertEqual(subscription.daily_alert_count, 1)
        self.assertEqual(subscription.daily_alert_date, today)
        self.assertIsNotNone(subscription.last_alert_at)
