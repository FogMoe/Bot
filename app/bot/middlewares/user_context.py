"""Ensure Telegram users are persisted in MySQL."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.core import User


class UserContextMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        session: AsyncSession = data["session"]
        from_user = getattr(event, "from_user", None)
        if from_user is None:
            return await handler(event, data)

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

        user.last_seen_at = datetime.utcnow()
        data["db_user"] = user
        return await handler(event, data)
