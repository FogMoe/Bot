"""Simple per-user throttle to prevent rapid-fire requests."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable, Deque, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, MessageReactionUpdated, TelegramObject

from app.config import BotSettings, get_settings


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self, settings: BotSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.window_seconds = self.settings.request_limit.interval_seconds
        self.max_requests = self.settings.request_limit.max_requests
        self._events: Dict[int, Deque[float]] = defaultdict(deque)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user_id = self._extract_user_id(event)
        if user_id is None:
            return await handler(event, data)

        if self.max_requests <= 0:
            return await handler(event, data)

        now = time.monotonic()
        bucket = self._events[user_id]

        while bucket and now - bucket[0] > self.window_seconds:
            bucket.popleft()

        if len(bucket) >= self.max_requests:
            await self._notify_limit(event)
            return None

        bucket.append(now)
        return await handler(event, data)

    @staticmethod
    def _extract_user_id(event: TelegramObject) -> int | None:
        if isinstance(event, Message) and event.from_user is not None:
            return event.from_user.id
        if isinstance(event, MessageReactionUpdated) and getattr(event, "user", None) is not None:
            return event.user.id
        return None

    @staticmethod
    async def _notify_limit(event: TelegramObject) -> None:
        text = "Too many requests, please slow down."
        if isinstance(event, Message):
            await event.answer(text, parse_mode=None)
        elif isinstance(event, MessageReactionUpdated):
            await event.bot.send_message(
                event.chat.id,
                text,
                reply_to_message_id=event.message_id,
                parse_mode=None,
            )


__all__ = ["ThrottleMiddleware"]
