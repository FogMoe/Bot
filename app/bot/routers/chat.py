"""Telegram chat handlers."""

from __future__ import annotations

import asyncio
import contextlib
import secrets

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.enums import ChatAction
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runner import AgentOrchestrator
from app.bot.utils.messages import iter_fragments
from app.config import get_settings
from app.db.models.core import SubscriptionCard, SubscriptionPlan, User
from app.i18n import I18nService
from app.services.conversations import ConversationService
from app.services.exceptions import CardNotFound
from app.services.memory import MemoryService
from app.services.subscriptions import SubscriptionService

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
        plan = subscription.plan or await session.get(SubscriptionPlan, subscription.plan_id)
        if plan:
            plan_name = plan.name
    greeting = i18n.gettext(
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
            i18n.gettext("activate.usage", locale=locale),
            parse_mode=None,
        )
        return

    code = parts[1].strip()
    service = SubscriptionService(session)
    try:
        subscription = await service.redeem_card(db_user, code)
    except CardNotFound:
        await message.answer(
            i18n.gettext("activate.invalid", locale=locale),
            parse_mode=None,
        )
        return

    plan = await session.get(SubscriptionPlan, subscription.plan_id)
    plan_name = plan.name if plan else "Pro"
    await message.answer(
        i18n.gettext(
            "activate.success",
            locale=locale,
            plan=plan_name,
            date=subscription.expires_at.strftime("%Y-%m-%d"),
        ),
        parse_mode=None,
    )


@router.message(Command("issuecard"))
async def handle_issue_card(
    message: Message,
    session: AsyncSession,
    db_user: User | None = None,
) -> None:
    if settings.admin_telegram_id is None or message.from_user is None:
        return
    if message.from_user.id != settings.admin_telegram_id:
        await message.answer("Unauthorized", parse_mode=None)
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Usage: /issuecard <plan_code> [days] [card_code]", parse_mode=None)
        return

    plan_code = parts[1].strip()
    duration_days: int | None = None
    provided_code: str | None = None
    if len(parts) >= 3:
        if parts[2].isdigit():
            duration_days = int(parts[2])
            if len(parts) >= 4:
                provided_code = parts[3].strip()
        else:
            provided_code = parts[2].strip()
            if len(parts) >= 4 and parts[3].isdigit():
                duration_days = int(parts[3])
    plan_stmt = select(SubscriptionPlan).where(SubscriptionPlan.code == plan_code)
    result = await session.execute(plan_stmt)
    plan = result.scalar_one_or_none()
    if plan is None:
        await message.answer(f"Plan {plan_code} not found", parse_mode=None)
        return

    card_code = provided_code or _generate_card_code(plan.code)

    card = SubscriptionCard(
        code=card_code,
        plan_id=plan.id,
        status="new",
        valid_days=duration_days,
        created_by_admin_id=db_user.id if db_user else None,
    )
    session.add(card)
    await session.flush()

    await message.answer(
        f"Card generated: {card_code}\nPlan: {plan.name}\nDuration: {duration_days or settings.subscriptions.subscription_duration_days} days",
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
    subscription_service = SubscriptionService(session)
    subscription = await subscription_service.get_active_subscription(db_user)
    if subscription is None:
        subscription = await subscription_service.ensure_default_subscription(db_user)
    plan = subscription.plan or await session.get(SubscriptionPlan, subscription.plan_id)
    subscription_level = (plan.code if plan and plan.code else (plan.name if plan else "unknown")).lower()
    user_profile = {
        "username": db_user.username or "",
        "first_name": db_user.first_name or "",
        "last_name": db_user.last_name or "",
        "subscription_level": subscription_level,
    }

    conversation = await conversation_service.get_or_create_active_conversation(db_user)
    user_text = message.text or ""
    history_record = await conversation_service.get_history_record(conversation)
    history = conversation_service.deserialize_history(history_record)
    prior_summary = await conversation_service.get_prior_summary(conversation)

    typing_task = asyncio.create_task(_send_typing_action(message))
    try:
        agent_result = await agent.run(
            user_id=db_user.id,
            conversation_id=conversation.id,
            history=history,
            latest_user_message=user_text,
            memory_service=memory_service,
            prior_summary=prior_summary,
            user_profile=user_profile,
        )
    except Exception as exc:
        await message.answer(
            i18n.gettext("chat.agent_error", locale=locale),
            parse_mode=None,
        )
        raise exc
    finally:
        typing_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await typing_task

    fragments = list(iter_fragments(agent_result.output))
    for idx, (plain_fragment, formatted_fragment) in enumerate(fragments):
        try:
            await message.answer(formatted_fragment, parse_mode="MarkdownV2")
        except Exception:
            await message.answer(plain_fragment, parse_mode=None)
    await conversation_service.process_agent_result(
        conversation,
        user=db_user,
        agent_result=agent_result,
        history_record=history_record,
        summarizer=agent.summarize_history,
    )


async def _send_typing_action(message: Message) -> None:
    try:
        while True:
            await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


async def _handle_non_text(
    message: Message,
    session: AsyncSession,
    db_user: User | None,
    kind: str,
) -> None:
    if db_user is None:
        return
    conversation_service = ConversationService(session)
    conversation = await conversation_service.get_or_create_active_conversation(db_user)
    payload = _format_non_text_payload(kind, message)
    i18n = I18nService(default_locale=settings.default_language)
    locale = db_user.language_code or settings.default_language
    reply_text = i18n.gettext("media.unsupported", locale=locale, kind=kind)
    history_record = await conversation_service.get_history_record(conversation)
    manual_history: list[ModelMessage] = conversation_service.deserialize_history(history_record)
    manual_history.append(
        ModelRequest(parts=[UserPromptPart(content=payload)])
    )
    manual_history.append(
        ModelResponse(parts=[TextPart(content=reply_text)])
    )
    await conversation_service.store_manual_history(
        conversation,
        user=db_user,
        messages=manual_history,
    )
    await message.answer(reply_text, parse_mode=None)


def _format_non_text_payload(kind: str, message: Message) -> str:
    parts = [f"[{kind.upper()}]"]
    if message.caption:
        parts.append(f"caption={message.caption}")
    if message.photo:
        parts.append(f"file_id={message.photo[-1].file_id}")
    if message.document:
        parts.append(f"file_id={message.document.file_id}")
    if message.video:
        parts.append(f"file_id={message.video.file_id}")
    if message.voice:
        parts.append(f"file_id={message.voice.file_id}")
    if message.audio:
        parts.append(f"file_id={message.audio.file_id}")
    if message.sticker:
        parts.append(f"sticker={message.sticker.file_unique_id}")
    if message.animation:
        parts.append(f"animation={message.animation.file_id}")
    if message.location:
        parts.append(f"location=({message.location.latitude},{message.location.longitude})")
    if message.contact:
        parts.append(f"contact={message.contact.phone_number}")
    if message.poll:
        parts.append("poll=received")
    return " ".join(parts)


def _generate_card_code(plan_code: str) -> str:
    part1 = secrets.token_hex(4).upper()
    part2 = secrets.token_hex(8).upper()
    return f"{plan_code.upper()}-{part1}-{part2}-FOGMOE"


@router.message(F.photo)
async def handle_photo(message: Message, session: AsyncSession, db_user: User | None = None) -> None:
    await _handle_non_text(message, session, db_user, kind="photo")


@router.message(F.document)
async def handle_document(message: Message, session: AsyncSession, db_user: User | None = None) -> None:
    await _handle_non_text(message, session, db_user, kind="document")


@router.message(F.video)
async def handle_video(message: Message, session: AsyncSession, db_user: User | None = None) -> None:
    await _handle_non_text(message, session, db_user, kind="video")


@router.message(F.voice)
@router.message(F.audio)
async def handle_audio(message: Message, session: AsyncSession, db_user: User | None = None) -> None:
    await _handle_non_text(message, session, db_user, kind="audio")


@router.message(F.sticker)
async def handle_sticker(message: Message, session: AsyncSession, db_user: User | None = None) -> None:
    await _handle_non_text(message, session, db_user, kind="sticker")


@router.message(F.animation)
async def handle_animation(message: Message, session: AsyncSession, db_user: User | None = None) -> None:
    await _handle_non_text(message, session, db_user, kind="animation")


@router.message(F.location)
async def handle_location(message: Message, session: AsyncSession, db_user: User | None = None) -> None:
    await _handle_non_text(message, session, db_user, kind="location")


@router.message(F.contact)
async def handle_contact(message: Message, session: AsyncSession, db_user: User | None = None) -> None:
    await _handle_non_text(message, session, db_user, kind="contact")


@router.message(F.poll)
async def handle_poll(message: Message, session: AsyncSession, db_user: User | None = None) -> None:
    await _handle_non_text(message, session, db_user, kind="poll")


@router.message(F.game)
async def handle_game(message: Message, session: AsyncSession, db_user: User | None = None) -> None:
    await _handle_non_text(message, session, db_user, kind="game")
