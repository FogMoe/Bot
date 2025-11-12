"""Application entrypoint."""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.agents.runner import AgentOrchestrator
from app.bot.middlewares import DbSessionMiddleware, RateLimitMiddleware, UserContextMiddleware
from app.bot.routers import setup_routers
from app.config import get_settings
from app.db.session import Database
from app.logging import configure_logging, logger


async def main() -> None:
    configure_logging()
    settings = get_settings()

    bot = Bot(
        token=settings.telegram_token.get_secret_value(),
        default=DefaultBotProperties(
            parse_mode=ParseMode.MARKDOWN_V2 if settings.enable_markdown_v2 else None
        ),
    )
    dp = Dispatcher()
    dp.include_router(setup_routers())

    database = Database(settings=settings)
    dp.update.outer_middleware(DbSessionMiddleware(database))
    dp.update.outer_middleware(UserContextMiddleware())
    dp.message.middleware(RateLimitMiddleware(settings))

    agent = AgentOrchestrator(settings=settings)

    logger.info("bot_starting", environment=settings.environment)
    await dp.start_polling(bot, agent=agent)


if __name__ == "__main__":
    asyncio.run(main())
