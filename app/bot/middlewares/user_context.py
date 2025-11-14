"""Ensure Telegram users are persisted in MySQL."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.core import User
from app.services.subscriptions import SubscriptionService
from app.utils.datetime import utc_now
from app.bot.utils.telegram import answer_with_retry
from app.config import get_settings
from app.i18n import I18nService


class UserContextMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        session: AsyncSession = data["session"]
        settings = get_settings()
        i18n = I18nService(default_locale=settings.default_language)
        from_user = getattr(event, "from_user", None)
        if from_user is None:
            return await handler(event, data)

        chat = getattr(event, "chat", None)
        if chat and chat.type != "private":
            locale = getattr(from_user, "language_code", None) or settings.default_language
            await answer_with_retry(
                getattr(event, "reply_to_message", event),
                i18n.gettext("group.not_supported", locale=locale),
                parse_mode=None,
            )
            return

        subscription_service = SubscriptionService(session)

        stmt = select(User).where(User.telegram_id == from_user.id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                telegram_id=from_user.id,
                username=from_user.username,
                first_name=from_user.first_name,
                last_name=from_user.last_name,
                language_code=from_user.language_code or "en",
            )
            session.add(user)
            await session.flush()

            await subscription_service.ensure_default_subscription(user)

        await subscription_service.expire_outdated_subscriptions(user)

        user.last_seen_at = utc_now()
        data["db_user"] = user
        return await handler(event, data)
