"""Startup seed helpers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BotSettings
from app.db.models.core import SubscriptionPlan
from app.utils.datetime import utc_now


async def ensure_subscription_plans(session: AsyncSession, settings: BotSettings) -> None:
    """Ensure default Free/Pro/Max plans exist and stay in sync."""

    default_plans = (
        {
            "code": "FREE",
            "name": "Free",
            "description": "Free tier",
            "hourly_message_limit": 10,
            "monthly_price": 0.0,
            "priority": 0,
            "is_default": True,
        },
        {
            "code": "PLUS",
            "name": "Plus",
            "description": "Plus tier",
            "hourly_message_limit": 25,
            "monthly_price": 3.0,
            "priority": 25,
            "is_default": False,
        },
        {
            "code": "PRO",
            "name": "Pro",
            "description": "Pro tier",
            "hourly_message_limit": 50,
            "monthly_price": 5.0,
            "priority": 50,
            "is_default": False,
        },
        {
            "code": "MAX",
            "name": "Max",
            "description": "Max tier",
            "hourly_message_limit": 200,
            "monthly_price": 20.0,
            "priority": 100,
            "is_default": False,
        },
    )

    for payload in default_plans:
        stmt = select(SubscriptionPlan).where(SubscriptionPlan.code == payload["code"])
        result = await session.execute(stmt)
        plan = result.scalar_one_or_none()
        now = utc_now()
        if plan:
            plan.name = payload["name"]
            plan.description = payload["description"]
            plan.hourly_message_limit = payload["hourly_message_limit"]
            plan.monthly_price = payload["monthly_price"]
            plan.priority = payload["priority"]
            plan.is_default = payload["is_default"]
            plan.is_active = True
            plan.updated_at = now
        else:
            session.add(
                SubscriptionPlan(
                    code=payload["code"],
                    name=payload["name"],
                    description=payload["description"],
                    hourly_message_limit=payload["hourly_message_limit"],
                    monthly_price=payload["monthly_price"],
                    priority=payload["priority"],
                    is_default=payload["is_default"],
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
            )

    await session.commit()


__all__ = ["ensure_subscription_plans"]
