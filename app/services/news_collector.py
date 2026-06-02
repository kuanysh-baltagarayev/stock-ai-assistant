"""News collection with sentiment, for ticker and macro/political context.

Markets react to economic and political news, so this module pulls structured
news from APIs and official feeds (never by scraping HTML pages):

- Alpha Vantage NEWS_SENTIMENT: per-ticker news with pre-computed AI sentiment.
- Finnhub company-news / market-news: headlines (free tier).
- GDELT: open global event/news database for macro and political stories.
- Official RSS (Federal Reserve, BLS): Tier-1 economic policy news.

All sources are best-effort and gated on their keys; without keys the relevant
source is simply skipped and an empty context is returned. Items are
de-duplicated and each source carries a reliability weight so a Fed release
counts for more than an anonymous blog.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib import error as urlerror
from urllib import parse
from urllib import request as urlrequest
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

_USER_AGENT = "stock-ai-assistant/1.0"
_ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
_FINNHUB_URL = "https://finnhub.io/api/v1"
_GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
_FED_PRESS_RSS = "https://www.federalreserve.gov/feeds/press_all.xml"

# Source reliability weights (0..1). Official policy sources outrank newswires,
# which outrank generic/unknown outlets.
_SOURCE_WEIGHTS: dict[str, float] = {
    "federal reserve": 1.0,
    "bureau of labor statistics": 1.0,
    "u.s. securities and exchange commission": 1.0,
    "reuters": 0.9,
    "associated press": 0.9,
    "bloomberg": 0.9,
    "the wall street journal": 0.85,
    "financial times": 0.85,
    "cnbc": 0.75,
    "marketwatch": 0.7,
    "barrons": 0.7,
    "yahoo": 0.6,
}
_DEFAULT_SOURCE_WEIGHT = 0.5

# Lightweight lexicon for sources that do not ship sentiment (Finnhub/GDELT/RSS).
_POSITIVE_TERMS = {
    "beat", "beats", "surge", "surges", "rally", "rallies", "gain", "gains",
    "jump", "jumps", "soar", "soars", "upgrade", "upgraded", "record", "profit",
    "growth", "strong", "boost", "optimistic", "tops", "outperform",
}
_NEGATIVE_TERMS = {
    "miss", "misses", "plunge", "plunges", "slump", "fall", "falls", "drop",
    "drops", "tumble", "tumbles", "downgrade", "downgraded", "loss", "losses",
    "weak", "warning", "warns", "lawsuit", "probe", "recession", "fear",
    "fears", "selloff", "cut", "cuts", "default", "sanction", "sanctions",
}


# Keyword → sector mapping for news tagging. An item matches a sector when any
# of its keywords appear in the lowercased title or summary.
_SECTOR_KEYWORDS: dict[str, list[str]] = {
    "Technology": [
        "ai ", "artificial intelligence", "chip", "semiconductor", "software", "cloud", "cybersecurity",
        "tech", "algorithm", "silicon valley", "antitrust tech", "big tech", "data center",
        "nvidia", "apple", "microsoft", "alphabet", "google", "meta", "amazon aws",
    ],
    "Financials": [
        "bank", "federal reserve", "fomc", "interest rate", "yield curve", "mortgage",
        "credit", "jpmorgan", "goldman sachs", "wells fargo", "citigroup", "blackrock",
        "treasury yield", "rate hike", "rate cut", "bond yield", "lending",
    ],
    "Energy": [
        "oil", "crude", "gas", "energy", "pipeline", "opec", "petroleum", "drilling",
        "lng", "exxon", "chevron", "bp", "shell", "refinery", "fossil fuel", "renewable energy",
    ],
    "Healthcare": [
        "fda", "drug", "pharma", "biotech", "vaccine", "clinical trial", "medicare",
        "medicaid", "hospital", "healthcare", "pfizer", "johnson & johnson", "merck",
        "abbvie", "eli lilly", "health insurance",
    ],
    "Consumer Discretionary": [
        "retail", "consumer spending", "amazon", "tesla", "auto", "automobile",
        "disney", "netflix", "starbucks", "mcdonald", "housing starts", "home depot",
    ],
    "Consumer Staples": [
        "food", "grocery", "walmart", "procter & gamble", "coca-cola", "pepsi",
        "staple", "agricultural commodity", "crop", "wheat", "corn",
    ],
    "Industrials": [
        "tariff", "trade war", "manufacturing", "import duty", "export restriction",
        "boeing", "defense", "aerospace", "supply chain", "infrastructure", "railroad",
        "caterpillar", "3m", "union pacific",
    ],
    "Materials": [
        "steel", "aluminum", "copper", "mining", "chemicals", "iron ore", "lithium",
        "raw material", "commodity price", "metals", "alcoa", "freeport",
    ],
    "Communication Services": [
        "telecom", "5g", "streaming", "social media", "content moderation",
        "at&t", "verizon", "comcast", "disney streaming", "youtube", "twitter", "tiktok",
    ],
    "Real Estate": [
        "reit", "commercial real estate", "housing market", "mortgage rate",
        "property", "rental", "home price", "zillow", "realty",
    ],
    "Utilities": [
        "utility", "power grid", "electricity", "natural gas utility", "duke energy",
        "southern company", "dominion energy", "nuclear power",
    ],
}


def _tag_sectors(title: str, summary: str | None = None) -> tuple[str, ...]:
    """Return sectors affected by a news item based on keyword matching."""
    text = (title + " " + (summary or "")).lower()
    matched = []
    for sector, keywords in _SECTOR_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            matched.append(sector)
    return tuple(matched)


def news_relevant_for_sectors(
    items: list["NewsItem"],
    sectors: list[str],
) -> list["NewsItem"]:
    """Filter news items to those relevant for the given sectors.

    Items with no sector tags are considered market-wide and always included.
    Items with sector tags are included only if they overlap with ``sectors``.
    If ``sectors`` is empty, all items are returned (subscriber has no sector info).
    """
    if not sectors:
        return items
    sector_set = set(sectors)
    return [
        item for item in items
        if not item.affected_sectors or sector_set.intersection(item.affected_sectors)
    ]


# Keywords that indicate political or regulatory risk rather than pure economics.
_POLITICAL_KEYWORDS = {
    "tariff", "tariffs", "trade war", "sanction", "sanctions", "antitrust",
    "regulation", "regulatory", "ban", "banned", "export restriction", "import ban",
    "geopolit", "election", "debt ceiling", "government shutdown", "executive order",
    "congress", "senate", "legislation", "sec fine", "doj", "ftc probe", "ftc",
    "national security", "espionage", "tiktok ban", "huawei", "iran", "china ban",
}


def political_risk_level_from_news(
    context: "NewsContext",
    *,
    min_abs_score: float = 0.2,
    min_weight: float = 0.6,
) -> str | None:
    """Derive a political/regulatory risk level from macro news items.

    Returns ``"high"``, ``"elevated"``, or ``None``.
    Only macro/market-category items with political keywords are considered.
    """
    political_items = [
        item for item in context.items
        if item.category in {"macro", "market"}
        and item.sentiment_score is not None
        and abs(item.sentiment_score) >= min_abs_score
        and item.source_weight >= min_weight
        and any(kw in item.title.lower() for kw in _POLITICAL_KEYWORDS)
    ]
    if len(political_items) >= 2:
        return "high"
    if len(political_items) == 1:
        return "elevated"
    return None


@dataclass(frozen=True)
class NewsItem:
    title: str
    url: str | None
    source: str | None
    published_at: datetime | None
    summary: str | None
    sentiment_score: float | None  # -1..1 (negative..positive)
    sentiment_label: str  # "positive" | "neutral" | "negative"
    relevance: float | None  # 0..1, ticker relevance when known
    category: str  # "ticker" | "market" | "macro"
    affected_sectors: tuple[str, ...] = field(default_factory=tuple)  # empty = all sectors

    @property
    def source_weight(self) -> float:
        return _source_weight(self.source)


@dataclass(frozen=True)
class NewsContext:
    summary: str | None = None
    overall_sentiment_score: float | None = None
    overall_sentiment_label: str = "neutral"
    items: list[NewsItem] = field(default_factory=list)


def build_news_context(
    symbol: str | None,
    settings: Any,
    *,
    include_macro: bool = True,
    timeout_seconds: float = 15.0,
    limit: int = 8,
) -> NewsContext:
    """Build a combined news context for a ticker and/or macro/political news.

    Returns an empty context (never raises) if sources are unavailable.
    """
    items: list[NewsItem] = []

    if symbol:
        items.extend(_fetch_ticker_news(symbol, settings, timeout_seconds, limit))
    if include_macro:
        items.extend(_fetch_macro_news(settings, timeout_seconds, limit))

    items = _dedupe(items)
    if not items:
        return NewsContext()

    items.sort(key=lambda item: (item.published_at or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    score = _aggregate_sentiment(items)
    label = _score_to_label(score)
    return NewsContext(
        summary=_build_summary(symbol, items, label),
        overall_sentiment_score=score,
        overall_sentiment_label=label,
        items=items[:limit],
    )


def high_impact_news(context: NewsContext, *, min_abs_score: float = 0.35, min_weight: float = 0.75) -> list[NewsItem]:
    """News strong enough and from a reliable enough source to drive an alert."""
    return [
        item
        for item in context.items
        if item.sentiment_score is not None
        and abs(item.sentiment_score) >= min_abs_score
        and item.source_weight >= min_weight
    ]


# --- Ticker news -----------------------------------------------------------


def _fetch_ticker_news(symbol: str, settings: Any, timeout: float, limit: int) -> list[NewsItem]:
    items = _fetch_alpha_vantage_news(symbol, settings, timeout, limit)
    if items:
        return items
    return _fetch_finnhub_company_news(symbol, settings, timeout, limit)


def _fetch_alpha_vantage_news(symbol: str, settings: Any, timeout: float, limit: int) -> list[NewsItem]:
    api_key = getattr(settings, "alpha_vantage_api_key", None)
    if not api_key:
        return []
    query = parse.urlencode(
        {
            "function": "NEWS_SENTIMENT",
            "tickers": symbol,
            "limit": str(max(1, min(limit * 2, 50))),
            "apikey": api_key,
        }
    )
    payload = _get_json(f"{_ALPHA_VANTAGE_URL}?{query}", timeout)
    if not isinstance(payload, dict):
        return []
    feed = payload.get("feed")
    if not isinstance(feed, list):
        return []

    items: list[NewsItem] = []
    for entry in feed:
        if not isinstance(entry, dict):
            continue
        score, relevance = _alpha_vantage_ticker_sentiment(entry, symbol)
        title = str(entry.get("title") or "").strip()
        summary = entry.get("summary")
        items.append(
            NewsItem(
                title=title,
                url=entry.get("url"),
                source=entry.get("source"),
                published_at=_parse_av_time(entry.get("time_published")),
                summary=summary,
                sentiment_score=score,
                sentiment_label=_score_to_label(score),
                relevance=relevance,
                category="ticker",
                affected_sectors=_tag_sectors(title, summary),
            )
        )
    return [item for item in items if item.title]


def _alpha_vantage_ticker_sentiment(entry: dict[str, Any], symbol: str) -> tuple[float | None, float | None]:
    for ticker_entry in entry.get("ticker_sentiment", []) or []:
        if not isinstance(ticker_entry, dict):
            continue
        if str(ticker_entry.get("ticker", "")).upper() == symbol.upper():
            return (
                _to_float(ticker_entry.get("ticker_sentiment_score")),
                _to_float(ticker_entry.get("relevance_score")),
            )
    return _to_float(entry.get("overall_sentiment_score")), None


def _fetch_finnhub_company_news(symbol: str, settings: Any, timeout: float, limit: int) -> list[NewsItem]:
    api_key = getattr(settings, "finnhub_api_key", None)
    if not api_key:
        return []
    today = datetime.now(timezone.utc).date()
    query = parse.urlencode(
        {
            "symbol": symbol,
            "from": (today - timedelta(days=14)).isoformat(),
            "to": today.isoformat(),
            "token": api_key,
        }
    )
    payload = _get_json(f"{_FINNHUB_URL}/company-news?{query}", timeout)
    if not isinstance(payload, list):
        return []
    return _finnhub_items(payload, category="ticker", limit=limit)


# --- Macro / political news ------------------------------------------------


def _fetch_macro_news(settings: Any, timeout: float, limit: int) -> list[NewsItem]:
    items: list[NewsItem] = []
    items.extend(_fetch_finnhub_market_news(settings, timeout, limit))
    items.extend(_fetch_gdelt_news(timeout, limit))
    items.extend(_fetch_fed_rss(timeout, limit))
    return items


def _fetch_finnhub_market_news(settings: Any, timeout: float, limit: int) -> list[NewsItem]:
    api_key = getattr(settings, "finnhub_api_key", None)
    if not api_key:
        return []
    query = parse.urlencode({"category": "general", "token": api_key})
    payload = _get_json(f"{_FINNHUB_URL}/news?{query}", timeout)
    if not isinstance(payload, list):
        return []
    return _finnhub_items(payload, category="market", limit=limit)


def _fetch_gdelt_news(timeout: float, limit: int) -> list[NewsItem]:
    query = parse.urlencode(
        {
            "query": "(stock market OR federal reserve OR inflation OR tariff OR economy) sourcelang:eng",
            "mode": "ArtList",
            "format": "json",
            "maxrecords": str(max(1, min(limit, 25))),
            "sort": "DateDesc",
        }
    )
    payload = _get_json(f"{_GDELT_URL}?{query}", timeout)
    if not isinstance(payload, dict):
        return []
    articles = payload.get("articles")
    if not isinstance(articles, list):
        return []

    items: list[NewsItem] = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        title = str(article.get("title") or "").strip()
        if not title:
            continue
        score = _lexicon_sentiment(title)
        items.append(
            NewsItem(
                title=title,
                url=article.get("url"),
                source=article.get("domain"),
                published_at=_parse_gdelt_time(article.get("seendate")),
                summary=None,
                sentiment_score=score,
                sentiment_label=_score_to_label(score),
                relevance=None,
                category="macro",
                affected_sectors=_tag_sectors(title),
            )
        )
    return items


def _fetch_fed_rss(timeout: float, limit: int) -> list[NewsItem]:
    raw = _get_text(_FED_PRESS_RSS, timeout)
    if not raw:
        return []
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return []

    items: list[NewsItem] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        summary_text = item.findtext("description") or None
        score = _lexicon_sentiment(title)
        items.append(
            NewsItem(
                title=title,
                url=(item.findtext("link") or None),
                source="Federal Reserve",
                published_at=_parse_rss_time(item.findtext("pubDate")),
                summary=summary_text,
                sentiment_score=score,
                sentiment_label=_score_to_label(score),
                relevance=None,
                category="macro",
                affected_sectors=_tag_sectors(title, summary_text),
            )
        )
        if len(items) >= limit:
            break
    return items


def _finnhub_items(payload: list[Any], *, category: str, limit: int) -> list[NewsItem]:
    items: list[NewsItem] = []
    for entry in payload[: max(1, limit * 2)]:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("headline") or "").strip()
        if not title:
            continue
        entry_summary = entry.get("summary")
        score = _lexicon_sentiment(f"{title} {entry_summary or ''}")
        published = entry.get("datetime")
        published_at = (
            datetime.fromtimestamp(int(published), tz=timezone.utc)
            if isinstance(published, (int, float)) and published
            else None
        )
        items.append(
            NewsItem(
                title=title,
                url=entry.get("url"),
                source=entry.get("source"),
                published_at=published_at,
                summary=entry_summary,
                sentiment_score=score,
                sentiment_label=_score_to_label(score),
                relevance=None,
                category=category,
                affected_sectors=_tag_sectors(title, entry_summary),
            )
        )
    return items


# --- Aggregation helpers ---------------------------------------------------


def _dedupe(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    unique: list[NewsItem] = []
    for item in items:
        key = (item.url or _normalize_title(item.title)).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _aggregate_sentiment(items: list[NewsItem]) -> float | None:
    weighted_sum = 0.0
    weight_total = 0.0
    for item in items:
        if item.sentiment_score is None:
            continue
        weight = item.source_weight * (item.relevance if item.relevance is not None else 1.0)
        weighted_sum += item.sentiment_score * weight
        weight_total += weight
    if weight_total == 0:
        return None
    return round(weighted_sum / weight_total, 4)


def _build_summary(symbol: str | None, items: list[NewsItem], label: str) -> str:
    scope = symbol.upper() if symbol else "рынка"
    ticker_count = sum(1 for item in items if item.category == "ticker")
    market_count = sum(1 for item in items if item.category == "market")
    macro_count = sum(1 for item in items if item.category == "macro")
    parts = [f"Новостной фон {scope}: {_label_ru(label)}"]
    if ticker_count:
        parts.append(f"{ticker_count} по компании")
    if market_count:
        parts.append(f"{market_count} рыночных")
    if macro_count:
        parts.append(f"{macro_count} макро/политика")
    return "; ".join(parts) + "."


def _source_weight(source: str | None) -> float:
    if not source:
        return _DEFAULT_SOURCE_WEIGHT
    key = source.strip().lower()
    for known, weight in _SOURCE_WEIGHTS.items():
        if known in key:
            return weight
    return _DEFAULT_SOURCE_WEIGHT


def _lexicon_sentiment(text: str) -> float | None:
    tokens = re.findall(r"[a-z']+", text.lower())
    if not tokens:
        return None
    positives = sum(1 for token in tokens if token in _POSITIVE_TERMS)
    negatives = sum(1 for token in tokens if token in _NEGATIVE_TERMS)
    if positives == 0 and negatives == 0:
        return 0.0
    return round((positives - negatives) / (positives + negatives), 4)


def _score_to_label(score: float | None) -> str:
    if score is None:
        return "neutral"
    if score >= 0.15:
        return "positive"
    if score <= -0.15:
        return "negative"
    return "neutral"


def _label_ru(label: str) -> str:
    return {"positive": "позитивный", "negative": "негативный"}.get(label, "нейтральный")


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


# --- HTTP / parsing primitives ---------------------------------------------


def _get_text(url: str, timeout: float) -> str | None:
    request = urlrequest.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urlrequest.urlopen(request, timeout=max(1, int(timeout))) as response:
            return response.read().decode("utf-8", "replace")
    except (urlerror.URLError, TimeoutError, ValueError):
        return None


def _get_json(url: str, timeout: float) -> Any:
    raw = _get_text(url, timeout)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_av_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_gdelt_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_rss_time(value: Any) -> datetime | None:
    if not value:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            parsed = datetime.strptime(str(value), fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
