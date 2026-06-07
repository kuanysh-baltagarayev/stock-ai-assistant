from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


Recommendation = str


class Fundamentals(BaseModel):
    company_name: str | None = None
    sector: str | None = None
    market_cap: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    revenue_growth: float | None = None
    profit_margins: float | None = None
    debt_to_equity: float | None = None


class TechnicalIndicators(BaseModel):
    change_1d_pct: float | None = None
    change_1m_pct: float | None = None
    change_6m_pct: float | None = None
    moving_average_50: float | None = None
    moving_average_200: float | None = None
    rsi: float | None = None
    volatility_pct: float | None = None
    max_drawdown_pct: float | None = None


class CalendarEvent(BaseModel):
    name: str
    scheduled_at: datetime | None = None
    window_start_at: datetime | None = None
    window_end_at: datetime | None = None
    note: str | None = None


class EventCalendar(BaseModel):
    summary: str | None = None
    upcoming_events: list[CalendarEvent] = Field(default_factory=list)


class SecFiling(BaseModel):
    form_type: str
    filing_date: str
    accession_number: str
    description: str | None = None
    sec_url: str | None = None


class SecFilingsContext(BaseModel):
    summary: str | None = None
    cik: int | None = None
    company_name: str | None = None
    fetched_at: datetime | None = None
    recent_filings: list[SecFiling] = Field(default_factory=list)


class NewsArticle(BaseModel):
    title: str
    url: str | None = None
    source: str | None = None
    published_at: datetime | None = None
    summary: str | None = None
    sentiment_score: float | None = None
    sentiment_label: str = "neutral"
    relevance: float | None = None
    category: str = "ticker"


class NewsContext(BaseModel):
    summary: str | None = None
    overall_sentiment_score: float | None = None
    overall_sentiment_label: str = "neutral"
    articles: list[NewsArticle] = Field(default_factory=list)


class Scores(BaseModel):
    momentum_score: float
    valuation_score: float
    risk_score: float
    final_score: float


class AnalyzeResponse(BaseModel):
    ticker: str
    generated_at: datetime
    price: float
    currency: str | None = None
    price_adjustment_policy: str | None = None
    fundamentals: Fundamentals
    technicals: TechnicalIndicators
    scores: Scores
    recommendation: Recommendation
    short_reason: str
    explanation: str
    source_provenance: "SourceProvenance | None" = None
    data_quality: "DataQualityFlags" = Field(default_factory=lambda: DataQualityFlags())
    fx: "FXNormalization | None" = None
    market_session: "MarketSession | None" = None
    event_calendar: "EventCalendar | None" = None
    sec_filings: "SecFilingsContext | None" = None
    news: "NewsContext | None" = None
    operation_notes: list[str] = Field(default_factory=list)
    score_decomposition: dict[str, Any] | None = None


class ScanRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1, max_length=100)

    @field_validator("tickers")
    @classmethod
    def normalize_tickers(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for ticker in value:
            symbol = ticker.strip().upper()
            if not symbol:
                continue
            if symbol not in seen:
                normalized.append(symbol)
                seen.add(symbol)
        if not normalized:
            raise ValueError("At least one non-empty ticker is required.")
        return normalized


class ScanResult(BaseModel):
    ticker: str
    price: float
    final_score: float
    momentum_score: float
    valuation_score: float
    risk_score: float
    confidence: float | None = None
    source_provider: str | None = None
    source_tier: str | None = None
    market_session_status: str | None = None
    freshness_state: str | None = None
    data_quality_summary: str | None = None
    stale: bool = False
    delayed: bool = False
    missing: bool = False
    source_disagreed: bool = False
    recommendation: Recommendation
    short_reason: str


class ScanError(BaseModel):
    ticker: str
    error: str


class ScanSummary(BaseModel):
    requested_count: int
    success_count: int
    error_count: int
    partial_failure: bool
    message: str
    failed_tickers: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ScanResponse(BaseModel):
    results: list[ScanResult]
    errors: list[ScanError] = Field(default_factory=list)
    summary: ScanSummary


class AnalysisSnapshotRead(BaseModel):
    id: int
    ticker: str
    company_name: str | None = None
    price: float | None = None
    final_score: float
    recommendation: Recommendation
    created_at: datetime


class AnalysisSnapshotDetail(AnalysisSnapshotRead):
    payload: dict[str, Any]


class InstrumentRead(BaseModel):
    id: int
    symbol: str
    provider_symbol: str | None = None
    exchange_code: str | None = None
    mic: str | None = None
    country: str | None = None
    timezone: str | None = None
    currency: str | None = None
    asset_type: str | None = None
    company_name: str | None = None
    sector: str | None = None
    industry: str | None = None
    primary_listing: str | None = None
    isin: str | None = None
    figi: str | None = None
    provider_aliases: list[str]
    last_seen_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProviderRead(BaseModel):
    id: int
    name: str
    source_url: str | None = None
    source_tier: str | None = None
    data_category: str | None = None
    capability_list: list[str]
    legal_terms_note: str | None = None
    cache_ttl_seconds: int | None = None
    retry_attempts: int | None = None
    failure_taxonomy: list[str]
    last_seen_at: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_failure_mode: str | None = None
    created_at: datetime
    updated_at: datetime


class CoverageResponse(BaseModel):
    supported_markets: list[str]
    supported_asset_classes: list[str]
    source_tiers: list[str]
    calendars: list[str]
    currencies: list[str]
    known_gaps: list[str]


class SourceProvenance(BaseModel):
    provider_name: str
    source_url: str | None = None
    source_tier: str | None = None
    data_category: str | None = None
    extraction_method: str | None = None
    parser_version: str | None = None
    observed_at: datetime | None = None
    published_at: datetime | None = None
    fetched_at: datetime | None = None
    confidence: float | None = None
    content_hash: str | None = None


class DataQualityFlags(BaseModel):
    stale: bool = False
    delayed: bool = False
    estimated: bool = False
    missing: bool = False
    source_disagreed: bool = False
    confidence: float = 1.0
    summary: str | None = None


class FXNormalization(BaseModel):
    base_currency: str | None = None
    quote_currency: str | None = None
    fx_rate_to_usd: float | None = None
    fx_source: str | None = None
    fx_timestamp: datetime | None = None
    fx_assumption_note: str | None = None


class MarketSession(BaseModel):
    timezone: str | None = None
    reference_time: datetime
    status: str
    is_open: bool
    market_open_at: datetime | None = None
    market_close_at: datetime | None = None
    freshness_state: str | None = None
    freshness_note: str | None = None


class HealthResponse(BaseModel):
    status: str
    app: str
    generated_at: datetime
    database: str


class ReadinessResponse(BaseModel):
    status: str
    app: str
    generated_at: datetime
    database: str
    checks: dict[str, str]


class RootResponse(BaseModel):
    app: str
    status: str
    version: str
    endpoints: list[str]
    docs_url: str
    health_url: str
    analyze_url_template: str


JsonDict = dict[str, Any]


AnalyzeResponse.model_rebuild()
