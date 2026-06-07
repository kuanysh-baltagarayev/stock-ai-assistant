"""Tests for coverage module — per-analysis source coverage summary."""

from __future__ import annotations

import unittest

from app.services.coverage import (
    build_coverage_summary,
    format_coverage_gap_line,
    format_coverage_detail_lines,
    get_coverage_matrix,
    format_coverage_lines,
    format_coverage_text,
)


class BuildCoverageSummaryTest(unittest.TestCase):
    """Tests for build_coverage_summary()."""

    def test_full_coverage(self):
        summary = build_coverage_summary(
            has_sec_filings=True,
            cik_available=True,
            has_news=True,
            has_macro_context=True,
            has_market_regime=True,
            provider_name="yfinance",
            source_tier="Tier 2",
            confidence=0.95,
        )
        self.assertEqual(summary["overall"], "full")
        self.assertEqual(
            summary["present_sources"],
            sorted(["market_data", "sec_filings", "news", "macro_context", "market_regime"]),
        )
        self.assertEqual(summary["missing_critical"], [])
        self.assertEqual(summary["missing_optional"], [])
        self.assertEqual(summary["degradation_flags"], [])
        self.assertEqual(summary["provider_summary"], "yfinance/Tier 2")
        self.assertEqual(summary["confidence"], 0.95)

    def test_full_without_optional_sources(self):
        """Only market_data present — coverage is partial when optional sources are expected."""
        summary = build_coverage_summary(
            cik_available=False,  # no CIK → sec_filings not expected
            confidence=0.9,
        )
        self.assertEqual(summary["overall"], "partial")
        self.assertEqual(summary["present_sources"], ["market_data"])

    def test_partial_missing_news(self):
        summary = build_coverage_summary(
            cik_available=True,
            has_sec_filings=True,
            has_news=False,
            has_macro_context=True,
            confidence=0.75,
        )
        self.assertEqual(summary["overall"], "partial")
        self.assertIn("news", summary["missing_optional"])

    def test_partial_missing_sec_and_news_cik_known(self):
        summary = build_coverage_summary(
            cik_available=True,
            has_sec_filings=False,
            has_news=False,
            confidence=0.85,
        )
        self.assertEqual(summary["overall"], "partial")
        self.assertIn("sec_filings", summary["missing_optional"])
        self.assertIn("news", summary["missing_optional"])

    def test_partial_low_confidence(self):
        summary = build_coverage_summary(
            confidence=0.5,
            has_macro_context=True,
        )
        self.assertEqual(summary["overall"], "partial")
        self.assertIn("пониженная уверенность", summary["degradation_flags"])

    def test_minimal_no_market_data_is_impossible(self):
        """market_data is always present — verify invariant."""
        summary = build_coverage_summary()
        self.assertEqual(summary["missing_critical"], [])

    def test_degradation_flags_aggregate(self):
        summary = build_coverage_summary(
            stale=True,
            delayed=True,
            source_disagreed=True,
            confidence=0.6,
        )
        flags = summary["degradation_flags"]
        self.assertIn("устаревшие данные", flags)
        self.assertIn("задержка данных", flags)
        self.assertIn("источники расходятся", flags)
        self.assertIn("пониженная уверенность", flags)

    def test_no_news_no_sec(self):
        summary = build_coverage_summary(
            cik_available=True,
            has_sec_filings=False,
            has_news=False,
            has_macro_context=False,
            has_market_regime=False,
        )
        self.assertIn("sec_filings", summary["missing_optional"])
        self.assertIn("news", summary["missing_optional"])
        self.assertIn("macro_context", summary["missing_optional"])
        self.assertIn("market_regime", summary["missing_optional"])

    def test_confidence_none(self):
        summary = build_coverage_summary(confidence=None)
        self.assertNotIn("пониженная уверенность", summary["degradation_flags"])


class FormatCoverageGapLineTest(unittest.TestCase):
    """Tests for format_coverage_gap_line()."""

    def test_full(self):
        summary = build_coverage_summary(
            has_sec_filings=True, cik_available=True, has_news=True,
            has_macro_context=True, has_market_regime=True, confidence=0.95,
        )
        self.assertEqual(format_coverage_gap_line(summary), "Покрытие: полное")

    def test_partial_with_gaps(self):
        summary = build_coverage_summary(
            cik_available=True,
            has_news=False,
            has_macro_context=False,
            confidence=0.75,
        )
        line = format_coverage_gap_line(summary)
        self.assertIsNotNone(line)
        self.assertIn("частичное", line)
        self.assertIn("новости", line)
        self.assertIn("макро-контекст", line)

    def test_partial_with_flags(self):
        summary = build_coverage_summary(
            stale=True,
            confidence=0.75,
        )
        line = format_coverage_gap_line(summary)
        self.assertIsNotNone(line)
        self.assertIn("частичное", line)
        self.assertIn("устаревшие данные", line)

    def test_none_input(self):
        self.assertIsNone(format_coverage_gap_line(None))


class FormatCoverageDetailLinesTest(unittest.TestCase):
    """Tests for format_coverage_detail_lines()."""

    def test_full(self):
        summary = build_coverage_summary(
            has_sec_filings=True,
            cik_available=True,
            has_news=True,
            has_macro_context=True,
            has_market_regime=True,
            confidence=0.95,
        )
        lines = format_coverage_detail_lines(summary)
        self.assertTrue(any("рыночные данные" in line for line in lines))
        self.assertTrue(any("full" in line for line in lines))

    def test_partial_shows_gaps(self):
        summary = build_coverage_summary(
            cik_available=True,
            has_news=False,
            confidence=0.7,
        )
        lines = format_coverage_detail_lines(summary)
        joined = " ".join(lines)
        self.assertIn("✗", joined)
        self.assertIn("новости", joined)

    def test_empty(self):
        self.assertEqual(format_coverage_detail_lines(None), [])


class CoverageMatrixTest(unittest.TestCase):
    """Tests for static coverage matrix functions."""

    def test_get_coverage_matrix_has_keys(self):
        matrix = get_coverage_matrix()
        self.assertIn("supported_markets", matrix)
        self.assertIn("known_gaps", matrix)

    def test_format_coverage_lines(self):
        lines = format_coverage_lines()
        self.assertGreater(len(lines), 0)
        self.assertTrue(any("Supported markets" in line for line in lines))

    def test_format_coverage_text(self):
        text = format_coverage_text()
        self.assertIn("Supported markets", text)
        self.assertTrue("known_gaps" in text or "Known gaps" in text)

    def test_custom_matrix(self):
        custom = {"supported_markets": ["test"], "supported_asset_classes": [], "source_tiers": [], "calendars": [], "currencies": [], "known_gaps": []}
        lines = format_coverage_lines(custom)
        self.assertIn("test", " ".join(lines))
