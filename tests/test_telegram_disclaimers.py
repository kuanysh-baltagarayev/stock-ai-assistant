from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
import unittest

from app.services.runtime_budget import reset_runtime_budgets
from app.services.telegram_bot import TelegramBotService


class TelegramDisclaimerTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_budgets()
        self.service = TelegramBotService(settings=SimpleNamespace())

    def tearDown(self) -> None:
        reset_runtime_budgets()

    def test_welcome_text_includes_first_use_disclaimer(self) -> None:
        text = self.service._welcome_text(is_first_use=True)

        self.assertIn("Важно: это исследовательский инструмент", text)
        self.assertIn("не финансовый совет", text)

    def test_welcome_text_without_first_use_is_short(self) -> None:
        text = self.service._welcome_text(is_first_use=False)

        self.assertNotIn("Важно: это исследовательский инструмент", text)

    def test_analysis_text_adds_contextual_disclaimer_for_major_alert(self) -> None:
        analysis = SimpleNamespace(
            ticker="AAPL",
            recommendation="HIGH_INTEREST",
            price=189.12,
            currency="USD",
            scores=SimpleNamespace(final_score=86.0, momentum_score=70.0, valuation_score=65.0, risk_score=40.0),
            short_reason="HIGH_INTEREST: sample reason.",
            explanation="Sample explanation.",
            source_provenance=SimpleNamespace(
                provider_name="yfinance",
                source_tier="Tier 2",
                fetched_at="2026-06-08T13:00:00Z",
                observed_at="2026-06-08T13:00:00Z",
            ),
            data_quality=SimpleNamespace(
                stale=True,
                delayed=True,
                source_disagreed=True,
                confidence=0.65,
                summary="fresh but delayed",
            ),
            market_session=SimpleNamespace(status="closed", freshness_state="delayed"),
        )

        text = self.service._analysis_text(analysis)

        self.assertIn("Крупный сигнал", text)
        self.assertIn("AAPL: Высокий интерес", text)
        self.assertIn("Данные: yfinance/Tier 2", text)
        self.assertIn("confidence 0.65", text)
        self.assertIn("Качество данных:", text)
        self.assertIn("Низкая уверенность данных", text)
        self.assertIn("Источники не совпадают", text)

    def test_digest_text_adds_contextual_disclaimer_for_risk_and_major_alerts(self) -> None:
        results = [
            SimpleNamespace(
                ticker="MSFT",
                recommendation="HIGH_INTEREST",
                final_score=83.0,
                price=101.0,
                short_reason="sample",
                risk_score=40.0,
            ),
            SimpleNamespace(
                ticker="NVDA",
                recommendation="HIGH_RISK",
                final_score=24.0,
                price=99.0,
                short_reason="sample",
                risk_score=78.0,
            ),
        ]

        text = self.service._digest_text(results, [])

        self.assertIn("Крупные сигналы (1)", text)
        self.assertIn("Рискованные сигналы (1)", text)

    def test_scan_text_surfaces_operation_summary_for_errors_and_notes(self) -> None:
        results = [
            SimpleNamespace(
                ticker="AAPL",
                recommendation="NEUTRAL",
                final_score=77.7,
                price=189.12,
                short_reason="sample reason",
                confidence=0.91,
                risk_score=35.0,
                source_provider="yfinance",
                source_tier="Tier 2",
                market_session_status="regular_open",
                freshness_state="fresh",
            )
        ]
        errors = [SimpleNamespace(ticker="NVDA", error="yfinance timeout")]

        text = self.service._scan_text(
            results,
            errors,
            summary_notes=["OpenAI response was unavailable, so a rule-based explanation was used."],
        )

        self.assertIn("Сводка операций: market-data: 1, OpenAI: 1", text)
        self.assertIn("Ошибки:", text)

    def test_scan_text_groups_briefing_and_shows_confidence(self) -> None:
        results = [
            SimpleNamespace(
                ticker="AAPL",
                recommendation="HIGH_INTEREST",
                final_score=84.0,
                price=189.12,
                short_reason="strong setup",
                confidence=0.92,
                risk_score=35.0,
                source_provider="yfinance",
                source_tier="Tier 2",
                market_session_status="regular_open",
                freshness_state="fresh",
            ),
            SimpleNamespace(
                ticker="NVDA",
                recommendation="CAUTION",
                final_score=43.0,
                price=120.0,
                short_reason="event risk",
                confidence=0.62,
                risk_score=78.0,
                source_provider="yfinance",
                source_tier="Tier 2",
                market_session_status="closed",
                freshness_state="stale",
            ),
        ]

        text = self.service._scan_text(results, [])

        self.assertIn("Ключевые сигналы:", text)
        self.assertIn("Риск/качество данных:", text)
        self.assertIn("уверенность 0.92", text)
        self.assertIn("yfinance/Tier 2", text)
        self.assertIn("regular_open/fresh", text)
        self.assertIn("высокий риск 78", text)

    def test_risk_text_surfaces_data_quality_warnings(self) -> None:
        snapshot = SimpleNamespace(
            payload={
                "scores": {
                    "risk_score": 78.0,
                    "final_score": 24.0,
                },
                "recommendation": "CAUTION",
                "data_quality": {
                    "confidence": 0.42,
                    "summary": "source disagreement detected",
                    "source_disagreed": True,
                    "stale": True,
                },
                "source_provenance": {
                    "provider_name": "yfinance",
                    "source_tier": "Tier 2",
                    "fetched_at": "2026-06-08T13:00:00Z",
                },
                "market_session": {"status": "closed", "freshness_state": "stale"},
                "short_reason": "sample",
                "explanation": "sample",
                "event_calendar": None,
            },
            final_score=24.0,
            recommendation="CAUTION",
            created_at=None,
        )

        with patch.object(self.service, "_latest_analysis_snapshot", return_value=snapshot):
            text = self.service._risk_text("NVDA")

        self.assertIn("Данные: yfinance/Tier 2", text)
        self.assertIn("freshness stale", text)
        self.assertIn("Quality warnings:", text)
        self.assertIn("Низкая уверенность данных", text)
        self.assertIn("Источники не совпадают", text)

    def test_send_message_respects_telegram_send_budget(self) -> None:
        service = TelegramBotService(
            settings=SimpleNamespace(
                telegram_bot_token="123456:abcdefghijklmnopqrstuvwxyzABCDEF",
                telegram_poll_timeout_seconds=1,
                telegram_send_budget=0,
            )
        )

        with patch.object(service, "_request_json") as request_mock:
            with self.assertRaises(RuntimeError) as exc:
                service._send_message_sync(123, "hello")

        self.assertIn("Telegram send budget exhausted", str(exc.exception))
        request_mock.assert_not_called()

    def test_status_text_includes_telegram_send_budget(self) -> None:
        service = TelegramBotService(
            settings=SimpleNamespace(
                telegram_bot_token="123456:abcdefghijklmnopqrstuvwxyzABCDEF",
                telegram_poll_timeout_seconds=1,
                telegram_send_budget=3,
                telegram_digest_interval_minutes=1440,
                telegram_allowed_chat_ids=[],
                telegram_default_tickers="AAPL,MSFT,NVDA",
            )
        )

        fake_session = SimpleNamespace(
            query=lambda *args, **kwargs: SimpleNamespace(
                filter=lambda *a, **k: SimpleNamespace(one_or_none=lambda: SimpleNamespace(
                    is_active=True,
                    last_alert_at=None,
                    watchlist_symbols=["AAPL"],
                ))
            ),
            close=lambda: None,
        )

        with patch("app.services.telegram_bot.SessionLocal", return_value=fake_session):
            text = service._status_text(123)

        self.assertIn("Telegram send budget", text)
        self.assertIn("3/3 осталось", text)
        self.assertIn("Список для /scan: AAPL, MSFT, NVDA", text)

    def test_coverage_text_lists_supported_and_known_gap_sections(self) -> None:
        text = self.service._coverage_text()

        self.assertIn("Coverage matrix:", text)
        self.assertIn("Supported markets:", text)
        self.assertIn("Known gaps:", text)
