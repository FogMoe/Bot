"""Telegram chat handlers."""

from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runner import AgentOrchestrator
from app.bot.utils.messages import iter_fragments
from app.config import get_settings
from app.db.models.core import SubscriptionPlan, User
from app.domain.models import MessageModel
from app.i18n import I18nService
from app.services.conversations import ConversationService
from app.services.exceptions import CardNotFound
from app.services.memory import MemoryService
from app.services.subscriptions import SubscriptionService
from app.utils.tokens import estimate_tokens

router = Router()
settings = get_settings()


@router.message(CommandStart())
async def handle_start(
    message: Message,
    session: AsyncSession,
    db_user: User | None = None,
) -> None:
    if db_user is None:
        return
    i18n = I18nService(default_locale=settings.default_language)
    locale = db_user.language_code or settings.default_language
    subscription_service = SubscriptionService(session)
    subscription = await subscription_service.get_active_subscription(db_user)
    plan_name = "Free"
    if subscription:
        plan = await session.get(SubscriptionPlan, subscription.plan_id)
        if plan:
            plan_name = plan.name
    greeting = await i18n.gettext(
        "start.greeting",
        locale=locale,
        name=message.from_user.full_name,
        plan=plan_name,
    )
    await message.answer(greeting, parse_mode=None)


@router.message(Command("activate"))
async def handle_activate(
    message: Message,
    session: AsyncSession,
    db_user: User | None = None,
) -> None:
    if db_user is None:
        return
    i18n = I18nService(default_locale=settings.default_language)
    locale = db_user.language_code or settings.default_language
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2:
        await message.answer(
            await i18n.gettext("activate.usage", locale=locale),
            parse_mode=None,
        )
        return

    code = parts[1].strip()
    service = SubscriptionService(session)
    try:
        subscription = await service.redeem_card(db_user, code)
    except CardNotFound:
        await message.answer(
            await i18n.gettext("activate.invalid", locale=locale),
            parse_mode=None,
        )
        return

    plan = await session.get(SubscriptionPlan, subscription.plan_id)
    plan_name = plan.name if plan else "Pro"
    await message.answer(
        await i18n.gettext(
            "activate.success",
            locale=locale,
            plan=plan_name,
            date=subscription.expires_at.strftime("%Y-%m-%d"),
        ),
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
    i18n = I18nService(default_locale=settings.default_language)
    locale = db_user.language_code or settings.default_language

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
        agent_result = await agent.run(
            user_id=db_user.id,
            conversation_id=conversation.id,
            messages=history_models,
            memory_service=memory_service,
        )
    except Exception as exc:
        await message.answer(
            await i18n.gettext("chat.agent_error", locale=locale),
            parse_mode=None,
        )
        raise exc

    fragments = list(iter_fragments(agent_result))
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
