from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services import news_collector as nc


def _settings(av: str | None = "av-key", finnhub: str | None = "fh-key") -> SimpleNamespace:
    return SimpleNamespace(alpha_vantage_api_key=av, finnhub_api_key=finnhub)


class NewsParsingTests(unittest.TestCase):
    def test_alpha_vantage_uses_ticker_sentiment(self) -> None:
        payload = {
            "feed": [
                {
                    "title": "Apple beats earnings",
                    "url": "https://x.com/a",
                    "source": "Reuters",
                    "time_published": "20260601T130000",
                    "summary": "Strong quarter",
                    "overall_sentiment_score": 0.1,
                    "ticker_sentiment": [
                        {
                            "ticker": "AAPL",
                            "relevance_score": "0.9",
                            "ticker_sentiment_score": "0.42",
                            "ticker_sentiment_label": "Bullish",
                        }
                    ],
                }
            ]
        }
        with patch.object(nc, "_get_json", return_value=payload):
            items = nc._fetch_alpha_vantage_news("AAPL", _settings(), 5.0, 5)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].sentiment_score, 0.42)
        self.assertEqual(items[0].relevance, 0.9)
        self.assertEqual(items[0].sentiment_label, "positive")
        self.assertEqual(items[0].category, "ticker")

    def test_finnhub_company_news_parsed(self) -> None:
        payload = [
            {
                "headline": "Company surges on upgrade",
                "url": "https://x.com/b",
                "source": "CNBC",
                "datetime": 1_780_000_000,
                "summary": "analyst upgrade",
            }
        ]
        with patch.object(nc, "_get_json", return_value=payload):
            items = nc._fetch_finnhub_company_news("AAPL", _settings(), 5.0, 5)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "CNBC")
        self.assertEqual(items[0].sentiment_label, "positive")  # surges + upgrade

    def test_gdelt_parsed(self) -> None:
        payload = {
            "articles": [
                {
                    "title": "Inflation fears trigger selloff",
                    "url": "https://x.com/c",
                    "domain": "reuters.com",
                    "seendate": "20260601T120000Z",
                }
            ]
        }
        with patch.object(nc, "_get_json", return_value=payload):
            items = nc._fetch_gdelt_news(5.0, 5)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].category, "macro")
        self.assertEqual(items[0].sentiment_label, "negative")  # fears + selloff

    def test_fed_rss_parsed(self) -> None:
        rss = (
            "<rss><channel>"
            "<item><title>FOMC statement</title>"
            "<link>https://federalreserve.gov/x</link>"
            "<pubDate>Mon, 01 Jun 2026 14:00:00 GMT</pubDate>"
            "<description>policy</description></item>"
            "</channel></rss>"
        )
        with patch.object(nc, "_get_text", return_value=rss):
            items = nc._fetch_fed_rss(5.0, 5)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "Federal Reserve")
        self.assertEqual(items[0].source_weight, 1.0)


class NewsAggregationTests(unittest.TestCase):
    def test_dedupe_by_url_and_title(self) -> None:
        items = [
            nc.NewsItem("A", "https://x/1", "S", None, None, 0.0, "neutral", None, "market"),
            nc.NewsItem("A", "https://x/1", "S", None, None, 0.0, "neutral", None, "market"),
            nc.NewsItem("Same Title", None, "S", None, None, 0.0, "neutral", None, "market"),
            nc.NewsItem("same title", None, "S", None, None, 0.0, "neutral", None, "market"),
        ]
        self.assertEqual(len(nc._dedupe(items)), 2)

    def test_weighted_sentiment_favours_reliable_source(self) -> None:
        items = [
            # Reliable, strongly negative
            nc.NewsItem("t1", "u1", "Federal Reserve", None, None, -0.8, "negative", None, "macro"),
            # Low-weight, mildly positive
            nc.NewsItem("t2", "u2", "randomblog", None, None, 0.2, "positive", None, "market"),
        ]
        score = nc._aggregate_sentiment(items)
        self.assertIsNotNone(score)
        self.assertLess(score, 0)  # Fed's negative outweighs the blog

    def test_lexicon_sentiment(self) -> None:
        self.assertGreater(nc._lexicon_sentiment("stocks rally and surge"), 0)
        self.assertLess(nc._lexicon_sentiment("market plunge and losses"), 0)
        self.assertEqual(nc._lexicon_sentiment("the company released a report"), 0.0)

    def test_high_impact_filtering(self) -> None:
        ctx = nc.NewsContext(
            items=[
                nc.NewsItem("strong", "u1", "Reuters", None, None, -0.5, "negative", None, "market"),
                nc.NewsItem("weak", "u2", "Reuters", None, None, -0.1, "neutral", None, "market"),
                nc.NewsItem("low source", "u3", "blog", None, None, -0.9, "negative", None, "market"),
            ]
        )
        impactful = nc.high_impact_news(ctx)
        self.assertEqual([i.title for i in impactful], ["strong"])


class NewsContextTests(unittest.TestCase):
    def test_noop_without_keys_and_no_macro(self) -> None:
        with patch.object(nc, "_get_json", return_value=None), patch.object(nc, "_get_text", return_value=None):
            ctx = nc.build_news_context("AAPL", _settings(av=None, finnhub=None), include_macro=False)
        self.assertEqual(ctx.items, [])
        self.assertEqual(ctx.overall_sentiment_label, "neutral")

    def test_build_context_combines_and_summarizes(self) -> None:
        av_payload = {
            "feed": [
                {
                    "title": "Apple ticker news",
                    "url": "https://x/av",
                    "source": "Reuters",
                    "time_published": "20260601T130000",
                    "ticker_sentiment": [
                        {"ticker": "AAPL", "relevance_score": "0.8", "ticker_sentiment_score": "0.3"}
                    ],
                }
            ]
        }
        gdelt_payload = {
            "articles": [
                {"title": "Economy news", "url": "https://x/g", "domain": "reuters.com", "seendate": "20260601T120000Z"}
            ]
        }

        def fake_json(url: str, timeout: float):
            if "alphavantage" in url:
                return av_payload
            if "gdelt" in url:
                return gdelt_payload
            return None  # finnhub market/company

        with patch.object(nc, "_get_json", side_effect=fake_json), patch.object(nc, "_get_text", return_value=None):
            ctx = nc.build_news_context("AAPL", _settings(), include_macro=True)

        self.assertGreaterEqual(len(ctx.items), 2)
        self.assertIn("AAPL", ctx.summary)
        categories = {item.category for item in ctx.items}
        self.assertIn("ticker", categories)
        self.assertIn("macro", categories)


class ScannerNewsIntegrationTests(unittest.TestCase):
    def test_build_news_disabled_returns_empty(self) -> None:
        from app.services import scanner

        payload, notes = scanner._build_news("AAPL", _settings(), include_news=False)
        self.assertIsNone(payload)
        self.assertEqual(notes, [])

    def test_build_news_maps_context_to_payload_and_notes(self) -> None:
        from app.services import scanner

        context = nc.NewsContext(
            summary="Новостной фон AAPL: негативный; 1 по компании.",
            overall_sentiment_score=-0.5,
            overall_sentiment_label="negative",
            items=[
                nc.NewsItem(
                    "Big lawsuit hits company", "https://x/1", "Reuters",
                    None, None, -0.6, "negative", 0.9, "ticker",
                )
            ],
        )
        with patch.object(scanner, "build_news_context", return_value=context):
            payload, notes = scanner._build_news("AAPL", _settings(), include_news=True)

        self.assertEqual(payload["overall_sentiment_label"], "negative")
        self.assertEqual(len(payload["articles"]), 1)
        self.assertEqual(payload["articles"][0]["source"], "Reuters")
        self.assertTrue(any("News:" in note for note in notes))
        self.assertTrue(any("High-impact news (negative" in note for note in notes))


class SectorTaggingTests(unittest.TestCase):
    def test_tech_keywords_tag_technology(self) -> None:
        sectors = nc._tag_sectors("Nvidia chip shortage slows AI data center builds")
        self.assertIn("Technology", sectors)

    def test_energy_keywords_tag_energy(self) -> None:
        sectors = nc._tag_sectors("OPEC cuts crude oil output amid global demand concerns")
        self.assertIn("Energy", sectors)

    def test_fed_news_tags_financials(self) -> None:
        sectors = nc._tag_sectors("Federal Reserve signals rate hike in September")
        self.assertIn("Financials", sectors)

    def test_tariff_news_tags_industrials(self) -> None:
        sectors = nc._tag_sectors("New tariff on steel imports announced by Commerce Dept")
        self.assertIn("Industrials", sectors)
        self.assertIn("Materials", sectors)

    def test_generic_news_returns_empty(self) -> None:
        sectors = nc._tag_sectors("Markets open higher on Tuesday")
        self.assertEqual(sectors, ())

    def test_summary_also_searched(self) -> None:
        sectors = nc._tag_sectors("Breaking news", "FDA approves new drug for cancer treatment")
        self.assertIn("Healthcare", sectors)


class NewsRoutingTests(unittest.TestCase):
    def _make_item(self, title: str, sectors: tuple[str, ...] = ()) -> nc.NewsItem:
        return nc.NewsItem(
            title=title, url=None, source=None, published_at=None, summary=None,
            sentiment_score=0.5, sentiment_label="positive", relevance=None,
            category="macro", affected_sectors=sectors,
        )

    def test_no_subscriber_sectors_returns_all(self) -> None:
        items = [
            self._make_item("Tech surge", ("Technology",)),
            self._make_item("Oil plunges", ("Energy",)),
            self._make_item("Generic market news"),
        ]
        result = nc.news_relevant_for_sectors(items, [])
        self.assertEqual(len(result), 3)

    def test_untagged_items_always_included(self) -> None:
        items = [
            self._make_item("Generic news"),  # no sectors
            self._make_item("Tech rally", ("Technology",)),
        ]
        result = nc.news_relevant_for_sectors(items, ["Financials"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "Generic news")

    def test_matching_sector_included(self) -> None:
        items = [
            self._make_item("Bank earnings beat", ("Financials",)),
            self._make_item("Oil rises", ("Energy",)),
        ]
        result = nc.news_relevant_for_sectors(items, ["Financials"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "Bank earnings beat")

    def test_overlapping_sector_included(self) -> None:
        items = [
            self._make_item("Tariffs hit steel", ("Industrials", "Materials")),
        ]
        result = nc.news_relevant_for_sectors(items, ["Materials", "Energy"])
        self.assertEqual(len(result), 1)

    def test_no_match_excluded(self) -> None:
        items = [
            self._make_item("Tech antitrust probe", ("Technology",)),
        ]
        result = nc.news_relevant_for_sectors(items, ["Energy"])
        self.assertEqual(len(result), 0)


if __name__ == "__main__":
    unittest.main()
