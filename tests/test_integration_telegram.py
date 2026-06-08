"""Integration tests for Telegram bot via mocked HTTP transport.

These tests instantiate the real TelegramBotService with a mocked HTTP
backend and verify that command handling produces expected output.
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import TelegramSubscription
from app.database import SessionLocal, init_db
from app.config import Settings
from app.services.telegram_bot import TelegramBotService
from app.services.market_data import MarketDataError


def _make_settings() -> Settings:
    return Settings(
        telegram_bot_token="test:fake-token",
        telegram_enabled=True,
        telegram_allowed_chat_ids=[12345],
    )


class TelegramIntegrationTest(unittest.TestCase):
    """Test Telegram bot command handling with mocked transport."""

    def setUp(self):
        init_db()
        self._clean_db()
        self.bot = TelegramBotService(settings=_make_settings())
        self.bot._offset = 0
        self.bot._started_at = datetime.now(timezone.utc)

        # Mock the HTTP transport so no real Telegram calls are made.
        self.bot._get_updates = MagicMock(return_value=[])  # type: ignore[method-assign]
        self.bot._send_message = AsyncMock()  # type: ignore[method-assign]
        self.bot._bot_request = MagicMock()  # type: ignore[method-assign]

        # Create a subscription for the test chat.
        self._ensure_subscription()

    def tearDown(self):
        self._clean_db()

    def _clean_db(self):
        db = SessionLocal()
        try:
            db.query(TelegramSubscription).delete()
            db.commit()
        finally:
            db.close()

    def _ensure_subscription(self):
        db = SessionLocal()
        try:
            sub = TelegramSubscription(
                chat_id=12345,
                is_active=True,
                watchlist_symbols=[],
            )
            db.add(sub)
            db.commit()
        finally:
            db.close()

    def _make_update(self, text: str) -> dict:
        return {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "chat": {"id": 12345},
                "from": {"username": "testuser"},
                "text": text,
            },
        }

    def _run(self, update: dict) -> None:
        """Run the async _handle_update synchronously."""
        asyncio.run(self.bot._handle_update(update))

    def test_start_command(self):
        self._run(self._make_update("/start"))
        self.bot._send_message.assert_called_once()
        args = self.bot._send_message.call_args[0]
        self.assertIn("Привет", args[1])

    def test_help_command(self):
        self._run(self._make_update("/help"))
        self.bot._send_message.assert_called_once()
        args = self.bot._send_message.call_args[0]
        self.assertIn("Доступно", args[1])

    def test_subscribe_command(self):
        self._run(self._make_update("/subscribe"))
        self.bot._send_message.assert_called_once()
        args = self.bot._send_message.call_args[0]
        self.assertIn("Подписка активирована", args[1])

    def test_unsubscribe_command(self):
        self._run(self._make_update("/unsubscribe"))
        self.bot._send_message.assert_called_once()
        args = self.bot._send_message.call_args[0]
        self.assertIn("Подписка отключена", args[1])

    def test_coverage_command(self):
        self._run(self._make_update("/coverage"))
        self.bot._send_message.assert_called_once()
        args = self.bot._send_message.call_args[0]
        self.assertIn("Coverage matrix", args[1])

    def test_health_command(self):
        self._run(self._make_update("/health"))
        self.bot._send_message.assert_called_once()
        args = self.bot._send_message.call_args[0]
        self.assertIn("Health", args[1])

    def test_providers_command(self):
        self._run(self._make_update("/providers"))
        self.bot._send_message.assert_called_once()
        args = self.bot._send_message.call_args[0]
        self.assertIn("провайдер", args[1].lower())

    def test_usage_command(self):
        self._run(self._make_update("/usage"))
        self.bot._send_message.assert_called_once()
        args = self.bot._send_message.call_args[0]
        self.assertIn("Использование", args[1])

    def test_watchlist_command(self):
        self._run(self._make_update("/watchlist"))
        self.bot._send_message.assert_called_once()
        args = self.bot._send_message.call_args[0]
        self.assertIn("список", args[1])

    def test_timezone_command(self):
        self._run(self._make_update("/timezone"))
        self.bot._send_message.assert_called_once()
        args = self.bot._send_message.call_args[0]
        self.assertIn("часовой пояс", args[1])

    def test_analyze_error_handling(self):
        """Test that /analyze with an error gives a proper message."""
        with patch.object(
            self.bot, "_analyze_and_persist",
            side_effect=MarketDataError("Could not determine current price for TEST."),
        ):
            self._run(self._make_update("/analyze TEST"))

        # Should have been called (progress message + error message).
        self.assertGreaterEqual(self.bot._send_message.call_count, 1)
        error_text = self.bot._send_message.call_args[0][1]
        self.assertIn("Не удалось проанализировать", error_text)

    def test_backtest_error_handling(self):
        """Test that /backtest with bad ticker gives a proper error."""
        with patch("app.services.backtesting.fetch_price_history_for_backtest", side_effect=MarketDataError("No data for INVALID")):
            self._run(self._make_update("/backtest INVALID"))
        self.assertGreaterEqual(self.bot._send_message.call_count, 1)
