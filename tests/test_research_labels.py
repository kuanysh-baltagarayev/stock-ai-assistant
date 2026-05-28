from __future__ import annotations

import unittest

from app.schemas import Fundamentals, TechnicalIndicators
from app.services.research_labels import (
    NEUTRAL_RESEARCH_LABELS,
    research_label_for_score,
    research_label_to_russian,
)
from app.services.scoring import score_stock


class ResearchLabelTests(unittest.TestCase):
    def test_label_thresholds_map_to_neutral_research_labels(self) -> None:
        self.assertEqual(research_label_for_score(85, 50), "HIGH_INTEREST")
        self.assertEqual(research_label_for_score(72, 60), "WATCH")
        self.assertEqual(research_label_for_score(55, 80), "NEUTRAL")
        self.assertEqual(research_label_for_score(45, 80), "CAUTION")
        self.assertEqual(research_label_for_score(20, 90), "HIGH_RISK")

    def test_score_stock_uses_neutral_research_labels_by_default(self) -> None:
        result = score_stock(
            price=100.0,
            technicals=TechnicalIndicators(),
            fundamentals=Fundamentals(),
        )

        self.assertIn(result.recommendation, NEUTRAL_RESEARCH_LABELS)
        self.assertEqual(result.recommendation, "NEUTRAL")
        self.assertTrue(result.short_reason.startswith("Neutral:"))

    def test_research_labels_translate_to_russian(self) -> None:
        self.assertEqual(research_label_to_russian("HIGH_INTEREST"), "Высокий интерес")
        self.assertEqual(research_label_to_russian("WATCH"), "Наблюдение")
        self.assertEqual(research_label_to_russian("NEUTRAL"), "Нейтрально")
        self.assertEqual(research_label_to_russian("CAUTION"), "Осторожно")
        self.assertEqual(research_label_to_russian("HIGH_RISK"), "Высокий риск")
