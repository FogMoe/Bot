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
from app.services.error_monitor import ErrorMonitor
from app.services.media_caption import MediaCaptionService
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
    error_monitor = ErrorMonitor(settings=settings)
    dp.errors.register(error_monitor)

    database = Database(settings=settings)

    # Seed subscription plans before starting services
    async with database.session() as seed_session:
        await ensure_subscription_plans(seed_session, settings)
    dp.update.outer_middleware(DbSessionMiddleware(database))
    throttle_middleware = ThrottleMiddleware(settings)
    user_context_middleware = UserContextMiddleware()
    rate_limit_middleware = RateLimitMiddleware(settings)

    dp.message.middleware(throttle_middleware)
    dp.message.middleware(user_context_middleware)
    dp.message.middleware(rate_limit_middleware)

    dp.message_reaction.middleware(throttle_middleware)
    dp.message_reaction.middleware(user_context_middleware)
    dp.message_reaction.middleware(rate_limit_middleware)

    # Create agent AFTER environment variables are set
    agent = AgentOrchestrator(settings=settings)
    media_caption_service = MediaCaptionService(settings=settings)

    logger.info("bot_starting", environment=settings.environment)
    await dp.start_polling(bot, agent=agent, media_caption_service=media_caption_service)


if __name__ == "__main__":
    asyncio.run(main())
