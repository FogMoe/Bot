"""Telegram chat handlers."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runner import AgentOrchestrator
from app.bot.utils.messages import iter_fragments
from app.db.models.core import SubscriptionPlan, User
from app.services.conversations import ConversationService
from app.services.memory import MemoryService
from app.services.subscriptions import SubscriptionService
from app.utils.tokens import estimate_tokens
from app.domain.models import MessageModel
from app.services.exceptions import CardNotFound

router = Router()


@router.message(CommandStart())
async def handle_start(
    message: Message,
    session: AsyncSession,
    db_user: User | None = None,
) -> None:
    if db_user is None:
        return
    subscription_service = SubscriptionService(session)
    subscription = await subscription_service.get_active_subscription(db_user)
    plan_name = "Free"
    if subscription:
        plan = await session.get(SubscriptionPlan, subscription.plan_id)
        if plan:
            plan_name = plan.name
    reply_text = (
        f"Hello, {message.from_user.full_name}!\n"
        f"Current plan: {plan_name}. Use /activate <card_code> to upgrade."
    )
    await message.answer(reply_text, parse_mode=None)


@router.message(Command("activate"))
async def handle_activate(
    message: Message,
    session: AsyncSession,
    db_user: User | None = None,
) -> None:
    if db_user is None:
        return
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2:
        await message.answer("Usage: /activate <card_code>", parse_mode=None)
        return

    code = parts[1].strip()
    service = SubscriptionService(session)
    try:
        subscription = await service.redeem_card(db_user, code)
    except CardNotFound:
        await message.answer("Invalid or expired card code.", parse_mode=None)
        return

    plan = await session.get(SubscriptionPlan, subscription.plan_id)
    plan_name = plan.name if plan else "Pro"
    await message.answer(
        f"Activated plan {plan_name} until {subscription.expires_at:%Y-%m-%d}.",
        parse_mode=None,
    )


@router.message(F.text)
async def handle_chat(
    message: Message,
    session: AsyncSession,
    agent: AgentOrchestrator,
    db_user: User | None = None,
) -> None:
    if db_user is None:
        return
    conversation_service = ConversationService(session)
    memory_service = MemoryService(session)

    conversation = await conversation_service.get_or_create_active_conversation(db_user)
    user_text = message.text or ""
    user_tokens = estimate_tokens(user_text)
    db_message = await conversation_service.add_message(
        conversation,
        user=db_user,
        role="user",
        content_markdown=user_text,
        content_plain=user_text,
        token_count=user_tokens,
    )

    history = await conversation_service.get_recent_messages(conversation, limit=20)
    history_models = [
        MessageModel(
            id=item.id,
            role=item.role,
            content=item.content_plain or item.content_markdown or "",
            sent_at=item.sent_at,
        )
        for item in history
    ]

    try:
        assistant_text = await agent.run(
            user_id=db_user.id,
            conversation_id=conversation.id,
            messages=history_models,
            memory_service=memory_service,
        )
    except Exception as exc:
        await message.answer("Agent failed to respond. Please try again later.", parse_mode=None)
        raise exc

    fragments = list(iter_fragments(assistant_text))
    for idx, (plain_fragment, formatted_fragment) in enumerate(fragments):
        await message.answer(formatted_fragment, parse_mode="MarkdownV2")
        await conversation_service.add_message(
            conversation,
            user=None,
            role="assistant",
            content_markdown=plain_fragment,
            content_plain=plain_fragment,
            token_count=estimate_tokens(plain_fragment),
            reply_to=db_message if idx == 0 else None,
            delivered_fragment_index=idx,
        )
