"""Telegram chat handlers."""

from __future__ import annotations

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
            i18n.gettext("chat.agent_error", locale=locale),
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
    await conversation_service.add_message(
        conversation,
        user=db_user,
        role="user",
        content_markdown=payload,
        content_plain=payload,
        token_count=estimate_tokens(payload),
    )
    i18n = I18nService(default_locale=settings.default_language)
    locale = db_user.language_code or settings.default_language
    await message.answer(
        i18n.gettext("media.unsupported", locale=locale, kind=kind),
        parse_mode=None,
    )


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
