from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import check_database, get_db
from app.schemas import (
    AnalysisSnapshotRead,
    AnalysisSnapshotDetail,
    AnalyzeResponse,
    HealthResponse,
    InstrumentRead,
    ReadinessResponse,
    RootResponse,
    ScanRequest,
    ScanResponse,
)
from app.services.history import get_snapshot_by_id, list_recent_snapshots
from app.services.market_data import MarketDataError
from app.services.instruments import get_instrument_by_symbol
from app.services.scanner import analyze_ticker, scan_tickers


router = APIRouter()


@router.get("/", response_model=RootResponse)
def root() -> RootResponse:
    settings = get_settings()
    return RootResponse(
        app=settings.app_name,
        status="ok",
        version="0.1.0",
        endpoints=[
            "/health",
            "/ready",
            "/analyze/{ticker}",
            "/scan",
            "/analyses/recent",
            "/analyses/{analysis_id}",
            "/instruments/{symbol}",
        ],
        docs_url="/docs",
        health_url="/health",
        analyze_url_template="/analyze/{ticker}",
    )


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        generated_at=datetime.now(timezone.utc),
        database=settings.database_url,
    )


@router.get("/ready", response_model=ReadinessResponse)
def ready() -> ReadinessResponse:
    settings = get_settings()
    try:
        check_database()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "not_ready",
                "checks": {"database": f"failed: {exc}"},
            },
        ) from exc

    return ReadinessResponse(
        status="ready",
        app=settings.app_name,
        generated_at=datetime.now(timezone.utc),
        database=settings.database_url,
        checks={"database": "ok"},
    )


@router.get("/analyze/{ticker}", response_model=AnalyzeResponse)
def analyze(ticker: str, db: Session = Depends(get_db)) -> AnalyzeResponse:
    try:
        return analyze_ticker(ticker, db=db, use_ai_explanation=True)
    except MarketDataError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/scan", response_model=ScanResponse)
def scan(payload: ScanRequest, db: Session = Depends(get_db)) -> ScanResponse:
    return scan_tickers(payload.tickers, db=db)


@router.get("/analyses/recent", response_model=list[AnalysisSnapshotRead])
def recent_analyses(
    limit: int = 10,
    ticker: str | None = None,
    db: Session = Depends(get_db),
) -> list[AnalysisSnapshotRead]:
    limit = max(1, min(limit, 100))
    snapshots = list_recent_snapshots(db, limit=limit, ticker=ticker)
    return [
        AnalysisSnapshotRead(
            id=item.id,
            ticker=item.ticker,
            company_name=item.company_name,
            price=item.price,
            final_score=item.final_score,
            recommendation=item.recommendation,
            created_at=item.created_at,
        )
        for item in snapshots
    ]


@router.get("/analyses/{analysis_id}", response_model=AnalysisSnapshotDetail)
def analysis_detail(analysis_id: int, db: Session = Depends(get_db)) -> AnalysisSnapshotDetail:
    snapshot = get_snapshot_by_id(db, analysis_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Analysis snapshot {analysis_id} not found")

    return AnalysisSnapshotDetail(
        id=snapshot.id,
        ticker=snapshot.ticker,
        company_name=snapshot.company_name,
        price=snapshot.price,
        final_score=snapshot.final_score,
        recommendation=snapshot.recommendation,
        created_at=snapshot.created_at,
        payload=snapshot.payload,
    )


@router.get("/instruments/{symbol}", response_model=InstrumentRead)
def instrument_detail(symbol: str, db: Session = Depends(get_db)) -> InstrumentRead:
    instrument = get_instrument_by_symbol(db, symbol)
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"Instrument {symbol.upper()} not found")

    return InstrumentRead(
        id=instrument.id,
        symbol=instrument.symbol,
        provider_symbol=instrument.provider_symbol,
        exchange_code=instrument.exchange_code,
        mic=instrument.mic,
        country=instrument.country,
        timezone=instrument.timezone,
        currency=instrument.currency,
        asset_type=instrument.asset_type,
        company_name=instrument.company_name,
        sector=instrument.sector,
        industry=instrument.industry,
        primary_listing=instrument.primary_listing,
        isin=instrument.isin,
        figi=instrument.figi,
        provider_aliases=instrument.provider_aliases or [],
        last_seen_at=instrument.last_seen_at,
        created_at=instrument.created_at,
        updated_at=instrument.updated_at,
    )
