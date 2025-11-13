"""Application entrypoint."""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from app.agents.runner import AgentOrchestrator
from app.bot.middlewares import (
    DbSessionMiddleware,
    RateLimitMiddleware,
    ThrottleMiddleware,
    UserContextMiddleware,
)
from app.bot.routers import setup_routers
from app.config import get_settings
from app.db.session import Database
from app.logging import configure_logging, logger
from app.services.seeds import ensure_subscription_plans


async def main() -> None:
    configure_logging()
    settings = get_settings()
    # CRITICAL: Apply environment variables BEFORE creating agent
    # Azure OpenAI provider needs these env vars to be set
    settings.llm.apply_environment()

    session = (
        AiohttpSession(proxy=settings.telegram_proxy) if settings.telegram_proxy else None
    )
    bot = Bot(
        token=settings.telegram_token.get_secret_value(),
        default=DefaultBotProperties(
            parse_mode=ParseMode.MARKDOWN_V2 if settings.enable_markdown_v2 else None
        ),
        session=session,
    )
    dp = Dispatcher()
    dp.include_router(setup_routers())

    database = Database(settings=settings)

    # Seed subscription plans before starting services
    async with database.session() as seed_session:
        await ensure_subscription_plans(seed_session, settings)
    dp.update.outer_middleware(DbSessionMiddleware(database))
    dp.message.middleware(ThrottleMiddleware(settings))
    dp.message.middleware(UserContextMiddleware())
    dp.message.middleware(RateLimitMiddleware(settings))

    # Create agent AFTER environment variables are set
    agent = AgentOrchestrator(settings=settings)

    logger.info("bot_starting", environment=settings.environment)
    await dp.start_polling(bot, agent=agent)


if __name__ == "__main__":
    asyncio.run(main())
