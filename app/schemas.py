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
    fundamentals: Fundamentals
    technicals: TechnicalIndicators
    scores: Scores
    recommendation: Recommendation
    short_reason: str
    explanation: str


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
    recommendation: Recommendation
    short_reason: str


class ScanError(BaseModel):
    ticker: str
    error: str


class ScanResponse(BaseModel):
    results: list[ScanResult]
    errors: list[ScanError] = Field(default_factory=list)


class AnalysisSnapshotRead(BaseModel):
    id: int
    ticker: str
    company_name: str | None = None
    price: float | None = None
    final_score: float
    recommendation: Recommendation
    created_at: datetime


class HealthResponse(BaseModel):
    status: str
    app: str
    generated_at: datetime
    database: str


class RootResponse(BaseModel):
    app: str
    status: str
    version: str
    endpoints: list[str]
    docs_url: str
    health_url: str
    analyze_url_template: str


JsonDict = dict[str, Any]
