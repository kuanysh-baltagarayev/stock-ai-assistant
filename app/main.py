from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.database import init_db
from app.services.telegram_bot import TelegramBotService


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    init_db()
    telegram_bot = TelegramBotService()
    await telegram_bot.start()
    yield
    await telegram_bot.stop()


app = FastAPI(
    title="Stock AI Assistant",
    version="0.1.0",
    description="Personal stock market research assistant. Not financial advice.",
    lifespan=lifespan,
)
app.include_router(router)
