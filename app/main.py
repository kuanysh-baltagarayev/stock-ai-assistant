from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging
from time import perf_counter

from fastapi import FastAPI
from starlette.requests import Request

from app.api.routes import router
from app.database import init_db
from app.logging_config import configure_logging
from app.services.telegram_bot import TelegramBotService


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging(force=True)
    logger.info("app_starting", extra={"component": "api"})
    init_db()
    telegram_bot = TelegramBotService()
    await telegram_bot.start()
    logger.info(
        "app_started",
        extra={"component": "api", "telegram_enabled": telegram_bot.enabled},
    )
    yield
    await telegram_bot.stop()
    logger.info("app_stopped", extra={"component": "api"})


app = FastAPI(
    title="Stock AI Assistant",
    version="0.1.0",
    description="Personal stock market research assistant. Not financial advice.",
    lifespan=lifespan,
)
app.include_router(router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request_failed",
            extra={
                "component": "api",
                "method": request.method,
                "path": request.url.path,
            },
        )
        raise

    duration_ms = round((perf_counter() - start) * 1000, 2)
    logger.info(
        "request_completed",
        extra={
            "component": "api",
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response
