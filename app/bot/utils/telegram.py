"""Telegram sending helpers with retry support."""

from __future__ import annotations

from typing import Any

from aiogram import Bot
from aiogram.types import Message

from app.logging import logger
from app.utils.retry import retry_async

TELEGRAM_SEND_MAX_ATTEMPTS = 3
TELEGRAM_SEND_BASE_DELAY = 0.3


async def answer_with_retry(message: Message, text: str, **kwargs: Any) -> Any:
    """Send a reply with retry/backoff."""

    async def _send():
        return await message.answer(text, **kwargs)

    return await retry_async(
        _send,
        max_attempts=TELEGRAM_SEND_MAX_ATTEMPTS,
        base_delay=TELEGRAM_SEND_BASE_DELAY,
        logger=logger,
        operation_name="telegram_answer",
    )


async def bot_send_with_retry(bot: Bot, *, chat_id: int, text: str, **kwargs: Any) -> Any:
    """Send a message via Bot with retry/backoff."""

    async def _send():
        return await bot.send_message(chat_id=chat_id, text=text, **kwargs)

    return await retry_async(
        _send,
        max_attempts=TELEGRAM_SEND_MAX_ATTEMPTS,
        base_delay=TELEGRAM_SEND_BASE_DELAY,
        logger=logger,
        operation_name="telegram_send_message",
    )


__all__ = ["answer_with_retry", "bot_send_with_retry"]
