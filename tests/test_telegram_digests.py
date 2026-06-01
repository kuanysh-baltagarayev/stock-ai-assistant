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
from app.services.news_collector import NewsContext
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
        # Prevent network calls to news APIs in all digest tests.
        news_patcher = patch("app.services.telegram_bot.build_news_context", return_value=NewsContext())
        news_patcher.start()
        self.addCleanup(news_patcher.stop)

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
            (datetime(2026, 7, 3, 16, 0, tzinfo=timezone.utc), "weekly_review"),
            (datetime(2026, 12, 24, 18, 30, tzinfo=timezone.utc), "close"),
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
            summary=SimpleNamespace(
                partial_failure=False,
                message="ok",
                failed_tickers=[],
                notes=["AAPL event calendar: Next earnings around 2026-06-12."],
            ),
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
        self.assertIn("event calendar", send_mock.await_args.args[1].lower())

    async def test_scheduled_digest_filters_low_confidence_results(self) -> None:
        self.service._upsert_subscription(
            1001,
            username="alice",
            active=True,
            watchlist_symbols=["AAPL"],
            preferences={"min_confidence": 0.8},
        )
        fake_scan = SimpleNamespace(
            results=[
                SimpleNamespace(
                    ticker="AAPL",
                    recommendation="NEUTRAL",
                    final_score=61.0,
                    price=189.12,
                    short_reason="high confidence signal",
                    confidence=0.93,
                ),
                SimpleNamespace(
                    ticker="MSFT",
                    recommendation="NEUTRAL",
                    final_score=54.0,
                    price=101.25,
                    short_reason="low confidence signal",
                    confidence=0.41,
                ),
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
        payload = send_mock.await_args.args[1]
        self.assertIn("Порог уверенности: 0.80", payload)
        self.assertIn("Скрыто низкоуверенных сигналов: 1", payload)
        self.assertIn("AAPL", payload)
        self.assertNotIn("MSFT", payload)

    async def test_scheduled_digest_skips_duplicate_alerts(self) -> None:
        self.service._upsert_subscription(
            1001,
            username="alice",
            active=True,
            watchlist_symbols=["AAPL"],
        )
        fake_scan = SimpleNamespace(
            results=[
                SimpleNamespace(
                    ticker="AAPL",
                    recommendation="NEUTRAL",
                    final_score=61.0,
                    price=189.12,
                    short_reason="sample reason",
                    confidence=0.93,
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
            await self.service._send_digest_to_active_subscribers()

        self.assertEqual(send_mock.await_count, 1)

    async def test_digest_includes_high_impact_news_block(self) -> None:
        from app.services.news_collector import NewsItem

        fake_scan = SimpleNamespace(
            results=[
                SimpleNamespace(
                    ticker="AAPL", recommendation="NEUTRAL",
                    final_score=61.0, price=189.12, short_reason="reason",
                )
            ],
            errors=[],
            summary=SimpleNamespace(partial_failure=False, message="ok", failed_tickers=[]),
        )
        high_impact_item = NewsItem(
            title="Fed raises rates unexpectedly",
            url="https://example.com/fed-news",
            source="Federal Reserve",
            published_at=None, summary=None,
            sentiment_score=-0.8, sentiment_label="negative",
            relevance=None, category="macro",
        )
        news_ctx = NewsContext(overall_sentiment_label="negative", items=[high_impact_item])
        send_mock = AsyncMock()

        with (
            patch("app.services.telegram_bot.scan_tickers", return_value=fake_scan),
            patch("app.services.telegram_bot.build_news_context", return_value=news_ctx),
            patch("app.services.telegram_bot.high_impact_news", return_value=[high_impact_item]),
            patch.object(self.service, "_send_message", send_mock),
            patch.object(self.service, "_scheduled_digest_mode", return_value="close"),
        ):
            await self.service._send_digest_to_active_subscribers()

        self.assertEqual(send_mock.await_count, 1)
        digest_text = send_mock.await_args.args[1]
        self.assertIn("📰 Важные новости:", digest_text)
        self.assertIn("Fed raises rates unexpectedly", digest_text)
        self.assertIn("Federal Reserve", digest_text)

    async def test_digest_deduplicates_when_news_unchanged(self) -> None:
        from app.services.news_collector import NewsItem

        fake_scan = SimpleNamespace(
            results=[
                SimpleNamespace(
                    ticker="AAPL", recommendation="NEUTRAL",
                    final_score=61.0, price=189.12, short_reason="reason",
                )
            ],
            errors=[],
            summary=SimpleNamespace(partial_failure=False, message="ok", failed_tickers=[]),
        )
        news_item = NewsItem(
            title="Big news", url="https://example.com/big-news",
            source="Reuters", published_at=None, summary=None,
            sentiment_score=-0.6, sentiment_label="negative",
            relevance=None, category="market",
        )
        news_ctx = NewsContext(items=[news_item])
        send_mock = AsyncMock()

        with (
            patch("app.services.telegram_bot.scan_tickers", return_value=fake_scan),
            patch("app.services.telegram_bot.build_news_context", return_value=news_ctx),
            patch("app.services.telegram_bot.high_impact_news", return_value=[news_item]),
            patch.object(self.service, "_send_message", send_mock),
            patch.object(self.service, "_scheduled_digest_mode", return_value="close"),
        ):
            await self.service._send_digest_to_active_subscribers()
            await self.service._send_digest_to_active_subscribers()

        self.assertEqual(send_mock.await_count, 1)
