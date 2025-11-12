"""Subscription and quota helpers."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BotSettings, get_settings
from app.db.models.core import SubscriptionCard, SubscriptionPlan, User, UserSubscription
from app.services.exceptions import CardNotFound


class SubscriptionService:
    def __init__(self, session: AsyncSession, settings: BotSettings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    async def get_active_subscription(self, user: User) -> UserSubscription | None:
        now = datetime.utcnow()
        stmt = (
            select(UserSubscription)
            .where(
                and_(
                    UserSubscription.user_id == user.id,
                    UserSubscription.status == "active",
                    or_(
                        UserSubscription.expires_at.is_(None),
                        UserSubscription.expires_at > now,
                    ),
                )
            )
            .order_by(UserSubscription.expires_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_hourly_limit(self, user: User) -> int:
        subscription = await self.get_active_subscription(user)
        if subscription:
            plan = await self.session.get(SubscriptionPlan, subscription.plan_id)
            if plan:
                return plan.hourly_message_limit
        # fallback
        return self.settings.subscriptions.free_hourly_limit

    async def redeem_card(self, user: User, code: str) -> UserSubscription:
        now = datetime.utcnow()
        card_stmt = (
            select(SubscriptionCard)
            .where(
                and_(
                    SubscriptionCard.code == code,
                    SubscriptionCard.status == "new",
                    or_(SubscriptionCard.expires_at.is_(None), SubscriptionCard.expires_at > now),
                )
            )
            .with_for_update()
        )
        result = await self.session.execute(card_stmt)
        card = result.scalar_one_or_none()
        if card is None:
            raise CardNotFound("Card not found or already redeemed.")

        card.status = "redeemed"
        card.redeemed_by_user_id = user.id
        card.redeemed_at = now

        expires_at = now + timedelta(days=self.settings.subscriptions.subscription_duration_days)
        subscription = UserSubscription(
            user_id=user.id,
            plan_id=card.plan_id,
            source_card_id=card.id,
            status="active",
            activated_at=now,
            expires_at=expires_at,
        )
        self.session.add(subscription)
        await self.session.flush()
        return subscription
