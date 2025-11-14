"""Enforce hourly quotas."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Sequence

from aiogram import BaseMiddleware
from aiogram.enums import MessageEntityType
from aiogram.types import Message, MessageEntity, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BotSettings, get_settings
from app.db.models.core import User
from app.i18n import I18nService
from app.services.exceptions import RateLimitExceeded
from app.services.rate_limit import RateLimiter
from app.services.subscriptions import SubscriptionService


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, settings: BotSettings | None = None) -> None:
        self.settings = settings or get_settings()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.from_user is None:
            return await handler(event, data)

        session: AsyncSession = data["session"]
        user: User | None = data.get("db_user")
        if user is None:
            return await handler(event, data)

        subscription_service = SubscriptionService(session, self.settings)
        hourly_limit = await subscription_service.get_hourly_limit(user)
        limiter = RateLimiter(
            session,
            retention_hours=self.settings.request_limit.window_retention_hours,
        )

        if self._should_consume_quota(event):
            try:
                await limiter.increment(user, hourly_limit)
            except RateLimitExceeded:
                i18n = I18nService(default_locale=self.settings.default_language)
                locale = user.language_code or self.settings.default_language
                await event.answer(
                    i18n.gettext("limit.exceeded", locale=locale),
                    parse_mode=None,
                )
                return None

        return await handler(event, data)

    @staticmethod
    def _should_consume_quota(message: Message) -> bool:
        """Ignore bare commands so only real chats count toward quota."""
        has_text = message.text or message.caption
        if has_text:
            return not RateLimitMiddleware._starts_with_command(
                message.entities if message.text else message.caption_entities
            )
        return bool(message.photo)

    @staticmethod
    def _starts_with_command(entities: Sequence[MessageEntity] | None) -> bool:
        for entity in entities or ():
            if entity.type == MessageEntityType.BOT_COMMAND and entity.offset == 0:
                return True
        return False
