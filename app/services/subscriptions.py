"""Subscription and quota helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import BotSettings, get_settings
from app.db.models.core import SubscriptionCard, SubscriptionPlan, User, UserSubscription
from app.services.exceptions import CardNotFound
from app.utils.datetime import utc_now

ACTIVE_STATUSES = {"active", "pending"}


class SubscriptionService:
    def __init__(self, session: AsyncSession, settings: BotSettings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    async def get_active_subscription(self, user: User) -> UserSubscription | None:
        now = utc_now()
        stmt = (
            select(UserSubscription)
            .options(selectinload(UserSubscription.plan))
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
            .order_by(UserSubscription.priority.desc(), UserSubscription.expires_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_hourly_limit(self, user: User) -> int:
        subscription = await self.get_active_subscription(user)
        if not subscription:
            subscription = await self.ensure_default_subscription(user)
        plan = subscription.plan
        if plan is None:
            plan = await self.session.get(SubscriptionPlan, subscription.plan_id)
        if plan:
            return plan.hourly_message_limit
        raise RuntimeError("No default subscription plan configured.")

    async def ensure_default_subscription(self, user: User) -> UserSubscription:
        """Make sure the user always has an active default plan record."""

        default_plan = await self._get_default_plan()
        if default_plan is None:
            raise RuntimeError("No default subscription plan configured.")

        stmt = select(UserSubscription).where(
            UserSubscription.user_id == user.id,
            UserSubscription.plan_id == default_plan.id,
        )
        result = await self.session.execute(stmt)
        subscription = result.scalar_one_or_none()
        now = utc_now()
        if subscription is None:
            subscription = UserSubscription(
                user_id=user.id,
                plan_id=default_plan.id,
                status="active",
                priority=default_plan.priority,
                activated_at=now,
                starts_at=now,
                expires_at=None,
            )
            self.session.add(subscription)
            subscription.plan = default_plan
        else:
            subscription.priority = default_plan.priority
            if subscription.status != "active":
                subscription.status = "active"
                subscription.activated_at = subscription.activated_at or now
                subscription.starts_at = subscription.starts_at or now
            subscription.expires_at = None
            if subscription.plan is None:
                subscription.plan = default_plan

        await self.session.flush()
        return subscription

    async def redeem_card(self, user: User, code: str) -> UserSubscription:
        from app.logging import logger
        
        now = utc_now()
        logger.info("redeem_card_start", user_id=user.id, code=code)
        
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
            logger.info("redeem_card_not_found", user_id=user.id, code=code)
            raise CardNotFound("Card not found or already redeemed.")

        logger.info(
            "redeem_card_found",
            user_id=user.id,
            card_id=card.id,
            plan_id=card.plan_id,
            valid_days=card.valid_days,
        )
        
        card.status = "redeemed"
        card.redeemed_by_user_id = user.id
        card.redeemed_at = now
        plan = await self.session.get(SubscriptionPlan, card.plan_id)
        if plan is None:
            logger.error("redeem_card_plan_not_found", card_id=card.id, plan_id=card.plan_id)
            raise CardNotFound("Associated plan no longer exists.")

        logger.info("redeem_card_plan_loaded", plan_code=plan.code, plan_name=plan.name)
        
        subs_stmt = (
            select(UserSubscription)
            .where(
                and_(
                    UserSubscription.user_id == user.id,
                    UserSubscription.status.in_(ACTIVE_STATUSES),
                )
            )
            .with_for_update()
        )
        existing_subs = list((await self.session.execute(subs_stmt)).scalars())
        logger.info("redeem_card_existing_subs", count=len(existing_subs))

        duration_days = card.valid_days or self.settings.subscriptions.subscription_duration_days
        duration = timedelta(days=duration_days)
        logger.info("redeem_card_duration", days=duration_days)

        stacked = self._extend_same_plan(existing_subs, plan, duration, now)
        if stacked:
            stacked.source_card_id = card.id
            logger.info(
                "redeem_card_stacked",
                subscription_id=stacked.id,
                expires_at=stacked.expires_at,
            )
            await self.session.flush()
            return stacked

        new_sub = UserSubscription(
            user_id=user.id,
            plan_id=plan.id,
            source_card_id=card.id,
            priority=plan.priority,
        )
        self.session.add(new_sub)
        self._schedule_new_subscription(new_sub, plan, existing_subs, duration, now)
        logger.info(
            "redeem_card_new_subscription",
            plan_id=new_sub.plan_id,
            status=new_sub.status,
            starts_at=new_sub.starts_at,
            expires_at=new_sub.expires_at,
        )
        await self.session.flush()
        return new_sub

    # Internal helpers -------------------------------------------------

    async def _get_default_plan(self) -> SubscriptionPlan | None:
        stmt = (
            select(SubscriptionPlan)
            .where(
                SubscriptionPlan.is_default.is_(True),
                SubscriptionPlan.is_active.is_(True),
            )
            .order_by(SubscriptionPlan.priority.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    def _extend_same_plan(
        self,
        subscriptions: Sequence[UserSubscription],
        plan: SubscriptionPlan,
        duration: timedelta,
        now: datetime,
    ) -> UserSubscription | None:
        candidates = [
            sub
            for sub in subscriptions
            if sub.plan_id == plan.id and sub.status in ACTIVE_STATUSES
        ]
        if not candidates:
            return None

        target = max(candidates, key=lambda sub: sub.expires_at or now)
        base = target.expires_at if target.expires_at and target.expires_at > now else now
        target.expires_at = (base or now) + duration
        if target.starts_at is None:
            target.starts_at = target.activated_at or now
        if target.expires_at and target.expires_at > now:
            target.status = "active" if (target.starts_at or now) <= now else "pending"
        target.priority = plan.priority
        return target

    def _schedule_new_subscription(
        self,
        new_sub: UserSubscription,
        plan: SubscriptionPlan,
        existing: Sequence[UserSubscription],
        duration: timedelta,
        now: datetime,
    ) -> None:
        blockers = [
            sub
            for sub in existing
            if sub.priority >= plan.priority and sub.status in ACTIVE_STATUSES
        ]
        start_at = now
        if blockers:
            start_at = max(start_at, max(self._subscription_end(sub, now) for sub in blockers))

        new_sub.priority = plan.priority
        if start_at <= now:
            new_sub.status = "active"
            new_sub.activated_at = now
            new_sub.starts_at = now
            new_sub.expires_at = now + duration
            self._delay_lower_priority(existing, plan.priority, new_sub.expires_at, now)
        else:
            new_sub.status = "pending"
            new_sub.starts_at = start_at
            new_sub.expires_at = start_at + duration

    def _delay_lower_priority(
        self,
        subscriptions: Sequence[UserSubscription],
        new_priority: int,
        tail_start: datetime,
        now: datetime,
    ) -> None:
        lower = [
            sub
            for sub in subscriptions
            if sub.priority < new_priority and sub.status in ACTIVE_STATUSES
        ]
        if not lower:
            return

        tail = tail_start
        for sub in sorted(lower, key=lambda s: (-s.priority, self._effective_start(s, now))):
            remaining = self._remaining_duration(sub, now)
            if remaining <= timedelta(0):
                continue
            sub.status = "pending"
            sub.starts_at = tail
            sub.expires_at = tail + remaining
            tail = sub.expires_at

    def _subscription_end(self, sub: UserSubscription, now: datetime) -> datetime:
        if sub.expires_at and sub.expires_at > now:
            return sub.expires_at
        if sub.expires_at:
            return sub.expires_at
        start = self._effective_start(sub, now)
        return start

    def _effective_start(self, sub: UserSubscription, now: datetime) -> datetime:
        if sub.starts_at:
            return sub.starts_at
        if sub.activated_at:
            return sub.activated_at
        return now

    def _remaining_duration(self, sub: UserSubscription, now: datetime) -> timedelta:
        if not sub.expires_at:
            return timedelta(0)
        if sub.status == "active":
            return max(timedelta(0), sub.expires_at - now)
        start = sub.starts_at or now
        return max(timedelta(0), sub.expires_at - start)
