"""Debug test for card activation issue."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest
from app.db.models.core import SubscriptionCard, SubscriptionPlan, User
from app.services.subscriptions import SubscriptionService
from app.utils.datetime import utc_now


@pytest.mark.asyncio
async def test_real_card_activation_flow(session):
    """Test the full card activation flow with real service."""
    # Create a plan
    plan = SubscriptionPlan(
        code="PLUS",
        name="Plus",
        description="Plus plan",
        hourly_message_limit=100,
        monthly_price=10.0,
        priority=10,
        is_default=False,
        is_active=True,
    )
    session.add(plan)
    await session.flush()

    # Create a user
    user = User(
        telegram_id=999888,
        username="testuser",
        language_code="en",
    )
    session.add(user)
    await session.flush()

    # Create a real card
    card = SubscriptionCard(
        code="PLUS-TEST-CARD-001",
        plan_id=plan.id,
        status="new",
        valid_days=30,
        expires_at=None,  # Card doesn't expire
    )
    session.add(card)
    await session.flush()

    # Now try to redeem the card
    service = SubscriptionService(session)
    subscription = await service.redeem_card(user, "PLUS-TEST-CARD-001")
    
    # Check that subscription was created properly
    assert subscription is not None
    assert subscription.user_id == user.id
    assert subscription.plan_id == plan.id
    assert subscription.expires_at is not None, "expires_at should be set!"
    assert subscription.status in ["active", "pending"]
    
    # Flush to ensure ID is assigned
    await session.flush()
    
    assert subscription.id is not None
    print(f"Subscription created: {subscription.id}")
    print(f"Status: {subscription.status}")
    print(f"Expires at: {subscription.expires_at}")
    print(f"Starts at: {subscription.starts_at}")
    print(f"Activated at: {subscription.activated_at}")
    
    # Check card status (no need to refresh, just check the object)
    assert card.status == "redeemed"
    assert card.redeemed_by_user_id == user.id
    assert card.redeemed_at is not None


@pytest.mark.asyncio
async def test_card_with_existing_subscription(session):
    """Test card activation when user already has a subscription."""
    # Create plans
    free_plan = SubscriptionPlan(
        code="FREE",
        name="Free",
        description="Free plan",
        hourly_message_limit=10,
        monthly_price=0.0,
        priority=0,
        is_default=True,
        is_active=True,
    )
    plus_plan = SubscriptionPlan(
        code="PLUS",
        name="Plus",
        description="Plus plan",
        hourly_message_limit=100,
        monthly_price=10.0,
        priority=10,
        is_default=False,
        is_active=True,
    )
    session.add_all([free_plan, plus_plan])
    await session.flush()

    # Create a user with default subscription
    user = User(
        telegram_id=999777,
        username="testuser2",
        language_code="en",
    )
    session.add(user)
    await session.flush()

    # Create default subscription for user
    service = SubscriptionService(session)
    default_sub = await service.ensure_default_subscription(user)
    await session.flush()
    
    assert default_sub.plan_id == free_plan.id
    assert default_sub.expires_at is None  # Free plan doesn't expire

    # Create a plus card
    card = SubscriptionCard(
        code="PLUS-UPGRADE-CARD-001",
        plan_id=plus_plan.id,
        status="new",
        valid_days=30,
    )
    session.add(card)
    await session.flush()

    # Redeem the plus card
    plus_sub = await service.redeem_card(user, "PLUS-UPGRADE-CARD-001")
    
    # Check that plus subscription was created
    assert plus_sub is not None
    assert plus_sub.user_id == user.id
    assert plus_sub.plan_id == plus_plan.id
    assert plus_sub.expires_at is not None, "Plus subscription should have expires_at!"
    
    await session.flush()
    
    print(f"\nPlus Subscription created: {plus_sub.id}")
    print(f"Status: {plus_sub.status}")
    print(f"Priority: {plus_sub.priority}")
    print(f"Expires at: {plus_sub.expires_at}")
    print(f"Starts at: {plus_sub.starts_at}")
    print(f"Activated at: {plus_sub.activated_at}")
