"""Simple per-user throttle to prevent rapid-fire requests."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable, Deque, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

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
        if not isinstance(event, Message) or event.from_user is None:
            return await handler(event, data)

        if self.max_requests <= 0:
            return await handler(event, data)

        user_id = event.from_user.id
        now = time.monotonic()
        bucket = self._events[user_id]

        while bucket and now - bucket[0] > self.window_seconds:
            bucket.popleft()

        if len(bucket) >= self.max_requests:
            await event.answer("Too many requests, please slow down.", parse_mode=None)
            return None

        bucket.append(now)
        return await handler(event, data)


__all__ = ["ThrottleMiddleware"]
