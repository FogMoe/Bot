"""Hour-based quota tracking."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.core import UsageHourlyQuota, User
from app.services.exceptions import RateLimitExceeded
from app.utils.datetime import utc_now


def _current_window_start(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0)


class RateLimiter:
    def __init__(self, session: AsyncSession, retention_hours: int | None = None) -> None:
        self.session = session
        self.retention_delta = (
            timedelta(hours=retention_hours) if retention_hours and retention_hours > 0 else None
        )

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
            await self._cleanup_old_windows(user.id, window_start)
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

    async def _cleanup_old_windows(self, user_id: int, window_start: datetime) -> None:
        if not self.retention_delta:
            return
        cutoff = window_start - self.retention_delta
        stmt = delete(UsageHourlyQuota).where(
            UsageHourlyQuota.user_id == user_id,
            UsageHourlyQuota.window_start < cutoff,
        )
        await self.session.execute(stmt)
