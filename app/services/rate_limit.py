"""Hour-based quota tracking."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.core import UsageHourlyQuota, User
from app.services.exceptions import RateLimitExceeded
from app.utils.datetime import utc_now


def _current_window_start(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0)


class RateLimiter:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def increment(
        self,
        user: User,
        hourly_limit: int,
        *,
        increment_messages: int = 1,
        increment_tools: int = 0,
    ) -> UsageHourlyQuota:
        now = utc_now()
        window_start = _current_window_start(now)

        stmt = (
            select(UsageHourlyQuota)
            .where(
                UsageHourlyQuota.user_id == user.id,
                UsageHourlyQuota.window_start == window_start,
            )
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        quota = result.scalar_one_or_none()
        if quota is None:
            quota = UsageHourlyQuota(
                user_id=user.id,
                window_start=window_start,
                message_count=0,
                tool_call_count=0,
                last_reset_at=window_start,
            )
            self.session.add(quota)

        if quota.message_count + increment_messages > hourly_limit:
            raise RateLimitExceeded(
                f"Hourly limit reached: {quota.message_count}/{hourly_limit}."
            )

        quota.message_count += increment_messages
        quota.tool_call_count += increment_tools
        quota.updated_at = now
        await self.session.flush()
        return quota
