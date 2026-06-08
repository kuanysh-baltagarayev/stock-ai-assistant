from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.schemas import DataQualityFlags, Scores
from app.services.score_decomposition import (
    ComponentAssessment,
    ScoreDecomposition,
    _bucket_reasons,
    _data_confidence_label,
    _event_risk_label,
    _normalize_data_quality,
    _technical_label,
    _valuation_label,
    decompose_scores,
    decomposition_as_payload,
    format_decomposition_lines,
)


# Reasons that span all three categories — used in integration tests.
_MIXED_REASONS = [
    # Momentum / technical
    "price is above MA50",
    "price is above MA200",
    "1-month momentum is positive",
    # Valuation
    "valuation looks reasonable by trailing P/E",
    "revenue growth is positive",
    "profit margins are healthy",
    # Risk
    "volatility is low",
    "max drawdown is limited",
    "upcoming earnings keep event risk elevated",
]


class ScoreDecompositionHelpersTests(unittest.TestCase):
    """Unit tests for the internal helper functions."""

    def test_technical_label_high(self) -> None:
        self.assertEqual(_technical_label(85), "благоприятный")
        self.assertEqual(_technical_label(70), "благоприятный")

    def test_technical_label_mixed(self) -> None:
        self.assertEqual(_technical_label(60), "смешанный")
        self.assertEqual(_technical_label(50), "смешанный")

    def test_technical_label_weak(self) -> None:
        self.assertEqual(_technical_label(30), "слабый")

    def test_valuation_label_attractive(self) -> None:
        self.assertEqual(_valuation_label(85), "привлекательная")
        self.assertEqual(_valuation_label(70), "привлекательная")

    def test_valuation_label_fair(self) -> None:
        self.assertEqual(_valuation_label(65), "адекватная")
        self.assertEqual(_valuation_label(50), "адекватная")

    def test_valuation_label_expensive(self) -> None:
        self.assertEqual(_valuation_label(30), "дороговато")

    def test_event_risk_label_low(self) -> None:
        self.assertEqual(_event_risk_label(20), "низкий")
        self.assertEqual(_event_risk_label(35), "низкий")

    def test_event_risk_label_moderate(self) -> None:
        self.assertEqual(_event_risk_label(45), "умеренный")
        self.assertEqual(_event_risk_label(55), "умеренный")

    def test_event_risk_label_elevated(self) -> None:
        self.assertEqual(_event_risk_label(65), "повышенный")

    def test_data_confidence_label_high(self) -> None:
        self.assertEqual(_data_confidence_label(0.9), "высокая")
        self.assertEqual(_data_confidence_label(0.8), "высокая")

    def test_data_confidence_label_medium(self) -> None:
        self.assertEqual(_data_confidence_label(0.7), "средняя")
        self.assertEqual(_data_confidence_label(0.6), "средняя")

    def test_data_confidence_label_low(self) -> None:
        self.assertEqual(_data_confidence_label(0.4), "низкая")


class ReasonBucketingTests(unittest.TestCase):
    """Tests for the keyword-based reason splitter."""

    def test_buckets_technical_reasons(self) -> None:
        reasons = ["price is above MA50", "RSI is overbought", "6-month trend is strong"]
        buckets = _bucket_reasons(reasons)
        self.assertEqual(len(buckets["technical"]), 3)
        self.assertEqual(len(buckets["valuation"]), 0)
        self.assertEqual(len(buckets["risk"]), 0)

    def test_buckets_valuation_reasons(self) -> None:
        reasons = ["trailing P/E is not meaningful", "revenue growth is strong", "profit margins are strong"]
        buckets = _bucket_reasons(reasons)
        self.assertEqual(len(buckets["valuation"]), 3)

    def test_buckets_risk_reasons(self) -> None:
        reasons = ["volatility is very high", "recent 8-K adds event risk", "upcoming earnings"]
        buckets = _bucket_reasons(reasons)
        self.assertEqual(len(buckets["risk"]), 3)

    def test_unknown_reason_goes_to_other(self) -> None:
        buckets = _bucket_reasons(["some random note"])
        self.assertEqual(len(buckets["other"]), 1)

    def test_empty_input_yields_empty_buckets(self) -> None:
        buckets = _bucket_reasons([])
        for key in ("technical", "valuation", "risk", "other"):
            self.assertEqual(len(buckets[key]), 0)


class NormalizeDataQualityTests(unittest.TestCase):
    """Tests for _normalize_data_quality."""

    def test_none_returns_default(self) -> None:
        dq = _normalize_data_quality(None)
        self.assertEqual(dq.confidence, 1.0)
        self.assertFalse(dq.stale)

    def test_flags_object_passes_through(self) -> None:
        original = DataQualityFlags(confidence=0.6, stale=True, missing=True)
        dq = _normalize_data_quality(original)
        self.assertEqual(dq.confidence, 0.6)
        self.assertTrue(dq.stale)
        self.assertTrue(dq.missing)

    def test_dict_normalizes(self) -> None:
        dq = _normalize_data_quality({"confidence": 0.45, "stale": True, "missing": True})
        self.assertEqual(dq.confidence, 0.45)
        self.assertTrue(dq.stale)
        self.assertTrue(dq.missing)

    def test_dict_ignores_extra_keys(self) -> None:
        dq = _normalize_data_quality({"confidence": 0.7, "unknown_key": "whatever"})
        self.assertEqual(dq.confidence, 0.7)


class DecomposeScoresIntegrationTests(unittest.TestCase):
    """Full integration tests for decompose_scores()."""

    def _make_scores(
        self,
        momentum: float = 70.0,
        valuation: float = 65.0,
        risk: float = 35.0,
        final: float = 75.0,
    ) -> Scores:
        return Scores(
            momentum_score=momentum,
            valuation_score=valuation,
            risk_score=risk,
            final_score=final,
        )

    def test_decompose_healthy_stock(self) -> None:
        decomp = decompose_scores(
            self._make_scores(momentum=80.0, valuation=75.0, risk=25.0, final=82.0),
            reasons=_MIXED_REASONS,
            final_label="HIGH_INTEREST",
        )
        self.assertEqual(decomp.technical.label, "благоприятный")
        self.assertEqual(decomp.valuation.label, "привлекательная")
        self.assertEqual(decomp.event_risk.label, "низкий")
        self.assertEqual(decomp.final_label, "HIGH_INTEREST")
        self.assertAlmostEqual(decomp.final_score, 82.0)

    def test_decompose_risky_stock(self) -> None:
        decomp = decompose_scores(
            self._make_scores(momentum=30.0, valuation=40.0, risk=80.0, final=30.0),
            reasons=[
                "price is below MA200",
                "trailing P/E is very high",
                "volatility is very high",
                "max drawdown is severe",
            ],
            final_label="HIGH_RISK",
        )
        self.assertEqual(decomp.technical.label, "слабый")
        self.assertEqual(decomp.valuation.label, "дороговато")
        self.assertEqual(decomp.event_risk.label, "повышенный")
        self.assertEqual(decomp.final_label, "HIGH_RISK")

    def test_empty_reasons_does_not_crash(self) -> None:
        decomp = decompose_scores(
            self._make_scores(),
            reasons=[],
            final_label="NEUTRAL",
        )
        self.assertEqual(decomp.technical.key_reasons, [])
        self.assertEqual(decomp.valuation.key_reasons, [])
        self.assertEqual(decomp.event_risk.key_reasons, [])

    def test_missing_technical_detected(self) -> None:
        """Default momentum=50.0 with no technical reasons → missing=True."""
        decomp = decompose_scores(
            self._make_scores(momentum=50.0, final=55.0),
            reasons=["valuation looks reasonable", "volatility is low"],
        )
        self.assertTrue(decomp.technical.missing)

    def test_missing_valuation_detected(self) -> None:
        """Default valuation=55.0 with no valuation reasons → missing=True."""
        decomp = decompose_scores(
            self._make_scores(valuation=55.0, final=55.0),
            reasons=["price is above MA50", "volatility is low"],
        )
        self.assertTrue(decomp.valuation.missing)

    def test_data_quality_degradation(self) -> None:
        decomp = decompose_scores(
            self._make_scores(final=80.0),
            reasons=_MIXED_REASONS,
            data_quality=DataQualityFlags(
                confidence=0.5,
                stale=True,
                delayed=True,
                missing=True,
                source_disagreed=True,
            ),
            final_label="HIGH_INTEREST",
        )
        self.assertEqual(decomp.data_confidence.label, "низкая")
        self.assertIn("неполные данные", decomp.data_confidence.key_reasons)
        self.assertIn("устаревшие данные", decomp.data_confidence.key_reasons)
        self.assertIn("задержка данных", decomp.data_confidence.key_reasons)
        self.assertIn("источники расходятся", decomp.data_confidence.key_reasons)
        self.assertTrue(decomp.data_confidence.missing)

    def test_high_confidence_no_flags(self) -> None:
        decomp = decompose_scores(
            self._make_scores(final=80.0),
            reasons=_MIXED_REASONS,
            data_quality=DataQualityFlags(confidence=0.95),
            final_label="HIGH_INTEREST",
        )
        self.assertEqual(decomp.data_confidence.label, "высокая")
        self.assertEqual(decomp.data_confidence.key_reasons, [])
        self.assertFalse(decomp.data_confidence.missing)

    def test_dict_data_quality_works(self) -> None:
        """Ensure _normalize_data_quality is called for dict inputs."""
        decomp = decompose_scores(
            self._make_scores(final=60.0),
            reasons=[],
            data_quality={"confidence": 0.35, "stale": True},
        )
        self.assertEqual(decomp.data_confidence.label, "низкая")
        self.assertTrue(decomp.data_confidence.missing)

    def test_no_data_quality_defaults_to_high_confidence(self) -> None:
        decomp = decompose_scores(
            self._make_scores(final=60.0),
            reasons=[],
            data_quality=None,
        )
        self.assertEqual(decomp.data_confidence.score, 100.0)  # 1.0 * 100
        self.assertEqual(decomp.data_confidence.label, "высокая")


class NoBuySellWordingTests(unittest.TestCase):
    """Acceptance criteria: no buy/sell-like wording in user-facing text."""

    _FORBIDDEN: tuple[str, ...] = ("buy", "sell", "продавать", "покупать", "продажа", "покупка")

    def _check_text(self, text: str, context: str) -> None:
        lower = text.lower()
        for word in self._FORBIDDEN:
            # Only flag whole-word matches
            if f" {word} " in f" {lower} " or lower.startswith(f"{word} ") or lower.endswith(f" {word}"):
                self.fail(f"'{context}' contains forbidden word '{word}': {text}")

    def test_component_labels_no_buy_sell(self) -> None:
        """All static Russian labels are free of buy/sell wording."""
        for label in (
            "благоприятный",
            "смешанный",
            "слабый",
            "привлекательная",
            "адекватная",
            "дороговато",
            "низкий",
            "умеренный",
            "повышенный",
            "высокая",
            "средняя",
            "низкая",
        ):
            self._check_text(label, f"label '{label}'")

    def test_format_decomposition_lines_no_buy_sell(self) -> None:
        decomp = ScoreDecomposition(
            technical=ComponentAssessment(score=75.0, label="благоприятный", key_reasons=["price is above MA50"]),
            valuation=ComponentAssessment(score=60.0, label="адекватная", key_reasons=["P/E looks fair"]),
            event_risk=ComponentAssessment(score=40.0, label="умеренный", key_reasons=["volatility is low"]),
            data_confidence=ComponentAssessment(score=95.0, label="высокая"),
            final_score=75.0,
            final_label="WATCH",
        )
        lines = format_decomposition_lines(decomp)
        for line in lines:
            self._check_text(line, "format_decomposition_lines")

    def test_decomposition_as_payload_no_buy_sell(self) -> None:
        decomp = ScoreDecomposition(
            technical=ComponentAssessment(score=75.0, label="благоприятный"),
            valuation=ComponentAssessment(score=60.0, label="адекватная"),
            event_risk=ComponentAssessment(score=40.0, label="умеренный"),
            data_confidence=ComponentAssessment(score=95.0, label="высокая"),
            final_score=75.0,
            final_label="WATCH",
        )
        payload = decomposition_as_payload(decomp)
        json_str = str(payload)
        self._check_text(json_str, "decomposition_as_payload")


class SerializationTests(unittest.TestCase):
    """Tests for dict serialization and pretty-printing."""

    def test_decomposition_as_payload_roundtrip(self) -> None:
        decomp = ScoreDecomposition(
            technical=ComponentAssessment(score=75.0, label="благоприятный", key_reasons=["above MA50"]),
            valuation=ComponentAssessment(score=60.0, label="адекватная", key_reasons=["P/E reasonable"]),
            event_risk=ComponentAssessment(score=40.0, label="умеренный", key_reasons=["low volatility"]),
            data_confidence=ComponentAssessment(score=90.0, label="высокая"),
            final_score=72.0,
            final_label="WATCH",
        )
        payload = decomposition_as_payload(decomp)
        self.assertEqual(payload["technical"]["label"], "благоприятный")
        self.assertEqual(payload["technical"]["score"], 75.0)
        self.assertEqual(payload["technical"]["key_reasons"], ["above MA50"])
        self.assertFalse(payload["technical"]["missing"])
        self.assertEqual(payload["final_score"], 72.0)
        self.assertEqual(payload["final_label"], "WATCH")
        self.assertIn("valuation", payload)
        self.assertIn("event_risk", payload)
        self.assertIn("data_confidence", payload)

    def test_format_decomposition_lines_structure(self) -> None:
        decomp = ScoreDecomposition(
            technical=ComponentAssessment(score=80.0, label="благоприятный", key_reasons=["above MA50", "above MA200"]),
            valuation=ComponentAssessment(score=70.0, label="привлекательная", key_reasons=["P/E reasonable"]),
            event_risk=ComponentAssessment(score=30.0, label="низкий", key_reasons=[]),
            data_confidence=ComponentAssessment(score=95.0, label="высокая"),
            final_score=78.0,
            final_label="WATCH",
        )
        lines = format_decomposition_lines(decomp)
        full = "\n".join(lines)
        self.assertIn("Наблюдение", full)
        self.assertIn("📊 тренд благоприятный", full)
        self.assertIn("💰 оценка привлекательная", full)
        self.assertIn("⚠️ риск низкий", full)
        self.assertIn("📋 данные высокая", full)
        self.assertIn("above MA50", full)
        self.assertIn("above MA200", full)

    def test_format_with_missing_component(self) -> None:
        decomp = ScoreDecomposition(
            technical=ComponentAssessment(score=50.0, label="смешанный", missing=True),
            valuation=ComponentAssessment(score=55.0, label="адекватная", missing=True),
            event_risk=ComponentAssessment(score=35.0, label="низкий"),
            data_confidence=ComponentAssessment(score=100.0, label="высокая"),
            final_score=55.0,
            final_label="NEUTRAL",
        )
        lines = format_decomposition_lines(decomp)
        full = "\n".join(lines)
        self.assertIn("Не хватает", full)
        self.assertIn("технические данные", full)

    def test_format_without_final_label(self) -> None:
        decomp = ScoreDecomposition(
            technical=ComponentAssessment(score=50.0, label="смешанный"),
            valuation=ComponentAssessment(score=55.0, label="адекватная"),
            event_risk=ComponentAssessment(score=35.0, label="низкий"),
            data_confidence=ComponentAssessment(score=100.0, label="высокая"),
            final_score=55.0,
            final_label="",
        )
        lines = format_decomposition_lines(decomp)
        full = "\n".join(lines)
        # Should show final score without the label after it
        self.assertIn("Оценка", full)
        self.assertIn("55", full)


class TelegramAnalysisTextDecompositionTests(unittest.TestCase):
    """Integration tests: _analysis_text renders decomposition when available."""

    _FORBIDDEN: tuple[str, ...] = ("buy", "sell", "продавать", "покупать", "продажа", "покупка")

    def _make_analysis(self, decomp_payload: dict | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            ticker="AAPL",
            recommendation="HIGH_INTEREST",
            price=189.12,
            currency="USD",
            scores=SimpleNamespace(
                final_score=82.0, momentum_score=75.0, valuation_score=70.0, risk_score=30.0
            ),
            short_reason="HIGH_INTEREST: strong technical and valuation setup.",
            explanation="Sample explanation text.",
            source_provenance=SimpleNamespace(
                provider_name="yfinance",
                source_tier="Tier 2",
                fetched_at="2026-06-08T13:00:00Z",
                observed_at="2026-06-08T13:00:00Z",
            ),
            data_quality=SimpleNamespace(
                stale=False,
                delayed=False,
                source_disagreed=False,
                confidence=0.92,
                summary="fresh data",
            ),
            market_session=SimpleNamespace(status="regular_open", freshness_state="fresh"),
            score_decomposition=decomp_payload,
        )

    def test_with_decomposition_shows_grouped_view(self) -> None:
        from app.services.score_decomposition import ScoreDecomposition, ComponentAssessment, decomposition_as_payload

        decomp = ScoreDecomposition(
            technical=ComponentAssessment(score=75.0, label="благоприятный", key_reasons=["above MA50"]),
            valuation=ComponentAssessment(score=70.0, label="привлекательная", key_reasons=["P/E reasonable"]),
            event_risk=ComponentAssessment(score=30.0, label="низкий"),
            data_confidence=ComponentAssessment(score=92.0, label="высокая"),
            final_score=82.0,
            final_label="HIGH_INTEREST",
        )
        analysis = self._make_analysis(decomp_payload=decomposition_as_payload(decomp))

        from app.services.telegram_bot import TelegramBotService
        from app.services.runtime_budget import reset_runtime_budgets

        reset_runtime_budgets()
        service = TelegramBotService(settings=SimpleNamespace())
        text = service._analysis_text(analysis)

        self.assertIn("📊 тренд благоприятный", text)
        self.assertIn("💰 оценка привлекательная", text)
        self.assertIn("⚠️ риск низкий", text)
        self.assertIn("📋 данные высокая", text)
        self.assertIn("above MA50", text)
        self.assertIn("P/E reasonable", text)
        # Should NOT show raw numeric score lines (old format without emoji)
        self.assertNotIn("Импульс:", text)
        self.assertNotIn("Риск:", text)
        # "Оценка стоимости:" now appears as the decomposition header line
        # Check the emoji-prefixed decomposition line is present instead
        self.assertIn("💰 оценка привлекательная", text)

    def test_with_decomposition_no_buy_sell(self) -> None:
        from app.services.score_decomposition import ScoreDecomposition, ComponentAssessment, decomposition_as_payload

        decomp = ScoreDecomposition(
            technical=ComponentAssessment(score=75.0, label="благоприятный"),
            valuation=ComponentAssessment(score=70.0, label="привлекательная"),
            event_risk=ComponentAssessment(score=30.0, label="низкий"),
            data_confidence=ComponentAssessment(score=92.0, label="высокая"),
            final_score=82.0,
            final_label="HIGH_INTEREST",
        )
        analysis = self._make_analysis(decomp_payload=decomposition_as_payload(decomp))

        from app.services.telegram_bot import TelegramBotService
        from app.services.runtime_budget import reset_runtime_budgets

        reset_runtime_budgets()
        service = TelegramBotService(settings=SimpleNamespace())
        text = service._analysis_text(analysis)

        lower = text.lower()
        for word in self._FORBIDDEN:
            if f" {word} " in f" {lower} " or lower.startswith(f"{word} ") or lower.endswith(f" {word}"):
                self.fail(f"Telegram analysis text contains forbidden word '{word}': {text}")

    def test_fallback_without_decomposition_shows_raw_scores(self) -> None:
        """When score_decomposition is None, default raw-score output is preserved."""
        analysis = self._make_analysis(decomp_payload=None)

        from app.services.telegram_bot import TelegramBotService
        from app.services.runtime_budget import reset_runtime_budgets

        reset_runtime_budgets()
        service = TelegramBotService(settings=SimpleNamespace())
        text = service._analysis_text(analysis)

        self.assertIn("Итоговая оценка: 82.00", text)
        self.assertIn("Импульс: 75.00", text)
        self.assertIn("Оценка стоимости: 70.00", text)
        self.assertIn("Риск: 30.00", text)


class ScoreDecompositionTelegramBotTest(unittest.TestCase):
    """Full integration: TelegramBotService._analysis_text with decomposition."""

    def setUp(self) -> None:
        from app.services.runtime_budget import reset_runtime_budgets
        reset_runtime_budgets()
        self.service = __import__(
            "app.services.telegram_bot", fromlist=["TelegramBotService"]
        ).TelegramBotService(settings=SimpleNamespace())

    def test_analysis_text_with_valid_decomposition(self) -> None:
        from app.services.score_decomposition import (
            ScoreDecomposition,
            ComponentAssessment,
            decomposition_as_payload,
        )

        decomp = ScoreDecomposition(
            technical=ComponentAssessment(score=75.0, label="благоприятный", key_reasons=["above MA50"]),
            valuation=ComponentAssessment(score=70.0, label="привлекательная", key_reasons=["P/E reasonable"]),
            event_risk=ComponentAssessment(score=30.0, label="низкий"),
            data_confidence=ComponentAssessment(score=92.0, label="высокая"),
            final_score=82.0,
            final_label="HIGH_INTEREST",
        )
        analysis = SimpleNamespace(
            ticker="AAPL",
            recommendation="HIGH_INTEREST",
            price=189.12,
            currency="USD",
            scores=SimpleNamespace(
                final_score=82.0, momentum_score=75.0, valuation_score=70.0, risk_score=30.0
            ),
            short_reason="HIGH_INTEREST: strong setup.",
            explanation="Sample.",
            source_provenance=SimpleNamespace(
                provider_name="yfinance", source_tier="Tier 2",
                fetched_at="2026-06-08T13:00:00Z", observed_at="2026-06-08T13:00:00Z",
            ),
            data_quality=SimpleNamespace(
                stale=False, delayed=False, source_disagreed=False,
                confidence=0.92, summary="fresh",
            ),
            market_session=SimpleNamespace(status="regular_open", freshness_state="fresh"),
            score_decomposition=decomposition_as_payload(decomp),
        )
        text = self.service._analysis_text(analysis)

        self.assertIn("📊 тренд благоприятный", text)
        self.assertIn("above MA50", text)
        self.assertNotIn("Импульс:", text)
        self.assertNotIn("Риск:", text)
        # "Оценка стоимости:" now appears as the emoji-prefixed decomposition header
        self.assertIn("💰 оценка привлекательная", text)


if __name__ == "__main__":
    unittest.main()
