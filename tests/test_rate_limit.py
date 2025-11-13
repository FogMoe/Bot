"""Rate limiter behaviour and integration tests."""

from __future__ import annotations

from types import SimpleNamespace
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.models.core import SubscriptionPlan, UsageHourlyQuota, User
from app.services.exceptions import RateLimitExceeded
from app.services.rate_limit import RateLimiter
from app.services.subscriptions import SubscriptionService
from app.utils.datetime import utc_now


def _stub_settings() -> SimpleNamespace:
    return SimpleNamespace(subscriptions=SimpleNamespace(subscription_duration_days=30))


async def _create_user(session) -> User:
    user = User(telegram_id=987654321)
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_rate_limiter_cleans_old_windows(session):
    user = await _create_user(session)
    limiter = RateLimiter(session, retention_hours=1)

    now = utc_now()
    old_window = (now - timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
    session.add(
        UsageHourlyQuota(
            user_id=user.id,
            window_start=old_window,
            message_count=1,
            tool_call_count=0,
            last_reset_at=old_window,
        )
    )
    await session.flush()

    await limiter.increment(user, hourly_limit=5)

    stmt = select(UsageHourlyQuota).where(UsageHourlyQuota.window_start == old_window)
    result = await session.execute(stmt)
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_subscription_and_rate_limit_flow(session):
    user = await _create_user(session)
    plan = SubscriptionPlan(
        code="FREE",
        name="Free",
        description="Free tier",
        hourly_message_limit=3,
        monthly_price=0.0,
        priority=0,
        is_default=True,
    )
    session.add(plan)
    await session.flush()

    subscription_service = SubscriptionService(session, settings=_stub_settings())
    hourly_limit = await subscription_service.get_hourly_limit(user)
    assert hourly_limit == plan.hourly_message_limit

    limiter = RateLimiter(session, retention_hours=24)
    for _ in range(hourly_limit):
        await limiter.increment(user, hourly_limit)

    with pytest.raises(RateLimitExceeded):
        await limiter.increment(user, hourly_limit)
