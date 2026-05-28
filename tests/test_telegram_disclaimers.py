from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.services.telegram_bot import TelegramBotService


class TelegramDisclaimerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = TelegramBotService(settings=SimpleNamespace())

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
        )

        text = self.service._analysis_text(analysis)

        self.assertIn("Крупный сигнал", text)
        self.assertIn("AAPL: Высокий интерес", text)

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
