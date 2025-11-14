"""Telegram chat handlers."""

from __future__ import annotations

import asyncio
import contextlib
import secrets
from datetime import timezone
from time import perf_counter

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.enums import ChatAction
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.usage import RunUsage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runner import AgentOrchestrator
from app.bot.utils.messages import iter_fragments
from app.bot.utils.telegram import answer_with_retry
from app.config import get_settings
from app.db.models.core import AgentRun, SubscriptionCard, SubscriptionPlan, User
from app.i18n import I18nService
from app.services.conversations import ConversationService
from app.services.exceptions import CardNotFound
from app.services.media_caption import MediaCaptionError, MediaCaptionService
from app.services.memory import MemoryService
from app.services.subscriptions import SubscriptionService
from app.logging import logger

router = Router()
settings = get_settings()
REPLY_CONTEXT_CHAR_LIMIT = 600
RESULT_SUMMARY_CHAR_LIMIT = 2000


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
    greeting = i18n.gettext(
        "start.greeting",
        locale=locale,
        name=message.from_user.full_name,
    )
    await answer_with_retry(message, greeting, parse_mode=None)


@router.message(Command("status"))
async def handle_status(
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
    if subscription is None:
        subscription = await subscription_service.ensure_default_subscription(db_user)
    plan = subscription.plan or await session.get(SubscriptionPlan, subscription.plan_id)
    plan_name = plan.name if plan else "Unknown"
    expires_at = subscription.expires_at
    if expires_at:
        expires_display = (
            expires_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if expires_at.tzinfo
            else expires_at.strftime("%Y-%m-%d %H:%M")
        )
    else:
        expires_display = i18n.gettext("status.no_expiration", locale=locale)

    status_text = subscription.status.capitalize()
    summary = i18n.gettext(
        "status.summary",
        locale=locale,
        plan=plan_name,
        status=status_text,
        expires_at=expires_display,
    )
    await answer_with_retry(message, summary, parse_mode=None)


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
        await answer_with_retry(
            message,
            i18n.gettext("activate.usage", locale=locale),
            parse_mode=None,
        )
        return

    code = parts[1].strip()
    logger.info("activate_card_attempt", user_id=db_user.id, code=code)
    service = SubscriptionService(session)
    try:
        subscription = await service.redeem_card(db_user, code)
        logger.info(
            "activate_card_redeemed",
            user_id=db_user.id,
            subscription_id=getattr(subscription, "id", None),
            plan_id=subscription.plan_id,
            expires_at=subscription.expires_at,
        )
    except CardNotFound as e:
        logger.info("activate_card_not_found", user_id=db_user.id, code=code, error=str(e))
        await answer_with_retry(
            message,
            i18n.gettext("activate.invalid", locale=locale),
            parse_mode=None,
        )
        return
    except Exception as e:
        logger.error(
            "activate_card_error",
            user_id=db_user.id,
            code=code,
            error=str(e),
            exc_info=True,
        )
        await answer_with_retry(
            message,
            i18n.gettext("activate.invalid", locale=locale),
            parse_mode=None,
        )
        return

    # Refresh subscription to get latest state
    try:
        await session.refresh(subscription)
    except Exception as e:
        logger.warning(
            "activate_refresh_failed",
            subscription_id=getattr(subscription, "id", None),
            error=str(e),
        )

    # Validate subscription has expires_at
    if subscription.expires_at is None:
        logger.error(
            "subscription_expires_missing",
            subscription_id=getattr(subscription, "id", None),
            plan_id=subscription.plan_id,
            status=getattr(subscription, "status", "unknown"),
        )
        await answer_with_retry(
            message,
            i18n.gettext("activate.invalid", locale=locale),
            parse_mode=None,
        )
        return

    # Get plan info and send success message
    plan = await session.get(SubscriptionPlan, subscription.plan_id)
    plan_name = plan.name if plan else "Pro"
    logger.info(
        "activate_card_success",
        user_id=db_user.id,
        plan=plan_name,
        expires_at=subscription.expires_at,
    )
    await answer_with_retry(
        message,
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
        await answer_with_retry(message, "Unauthorized", parse_mode=None)
        return

    parts = message.text.split()
    if len(parts) < 2:
        await answer_with_retry(
            message,
            "Usage: /issuecard <plan_code> [days] [card_code]",
            parse_mode=None,
        )
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
        await answer_with_retry(message, f"Plan {plan_code} not found", parse_mode=None)
        return

    card_code = provided_code or _generate_card_code(plan.code)
    effective_days = duration_days if duration_days is not None else settings.subscriptions.subscription_duration_days

    card = SubscriptionCard(
        code=card_code,
        plan_id=plan.id,
        status="new",
        valid_days=effective_days,
        created_by_admin_id=db_user.id if db_user else None,
    )
    session.add(card)
    await session.flush()

    await answer_with_retry(
        message,
        f"Card generated: {card_code}\nPlan: {plan.name}\nDuration: {effective_days} days",
        parse_mode=None,
    )


@router.message(Command("new"))
async def handle_new_conversation(
    message: Message,
    session: AsyncSession,
    agent: AgentOrchestrator,
    db_user: User | None = None,
) -> None:
    if db_user is None:
        return

    i18n = I18nService(default_locale=settings.default_language)
    locale = db_user.language_code or settings.default_language
    conversation_service = ConversationService(session)

    conversation = await conversation_service.get_or_create_active_conversation(db_user)
    history_record = await conversation_service.get_history_record(conversation)
    history = conversation_service.deserialize_history(history_record)

    summary_text: str | None = None
    if history:
        summary_text = await agent.summarize_history(history)
        await conversation_service.archive_full_history(
            conversation,
            user=db_user,
            messages=history,
            summary_text=summary_text,
        )

    await conversation_service.mark_conversation_archived(conversation)
    await conversation_service.delete_history(conversation)
    await conversation_service.create_conversation(db_user)

    if summary_text:
        archived_text = i18n.gettext("new.archived", locale=locale)
        await answer_with_retry(message, archived_text, parse_mode=None)
    else:
        no_history_text = i18n.gettext("new.no_history", locale=locale)
        await answer_with_retry(message, no_history_text, parse_mode=None)


@router.message(F.text)
async def handle_chat(
    message: Message,
    session: AsyncSession,
    agent: AgentOrchestrator,
    db_user: User | None = None,
) -> None:
    if db_user is None:
        return
    user_text = _compose_user_input_text(message)
    await _process_user_prompt(
        message,
        session=session,
        agent=agent,
        db_user=db_user,
        user_text=user_text,
    )


async def _process_user_prompt(
    message: Message,
    *,
    session: AsyncSession,
    agent: AgentOrchestrator,
    db_user: User,
    user_text: str,
) -> None:
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
    history_record = await conversation_service.get_history_record(conversation)
    history = conversation_service.deserialize_history(history_record)
    prior_summary = await conversation_service.get_prior_summary(conversation)

    async def notify_tool_usage(text: str) -> None:
        try:
            await answer_with_retry(message, text, parse_mode=None)
        except Exception:
            logger.warning("tool_notification_send_failed", text=text)

    typing_task = asyncio.create_task(_send_typing_action(message))
    started_at = perf_counter()
    try:
        agent_result = await agent.run(
            user_id=db_user.id,
            conversation_id=conversation.id,
            session=session,
            history=history,
            latest_user_message=user_text,
            memory_service=memory_service,
            prior_summary=prior_summary,
            user_profile=user_profile,
            tool_notification_cb=notify_tool_usage,
        )
        latency_ms = int((perf_counter() - started_at) * 1000)
    except Exception as exc:
        await answer_with_retry(
            message,
            i18n.gettext("chat.agent_error", locale=locale),
            parse_mode=None,
        )
        raise exc
    finally:
        typing_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await typing_task

    usage = agent_result.usage()
    fragments = list(iter_fragments(agent_result.output))
    for idx, (plain_fragment, formatted_fragment) in enumerate(fragments):
        try:
            await answer_with_retry(message, formatted_fragment, parse_mode="MarkdownV2")
        except Exception:
            await answer_with_retry(message, plain_fragment, parse_mode=None)
    await conversation_service.process_agent_result(
        conversation,
        user=db_user,
        agent_result=agent_result,
        history_record=history_record,
        summarizer=agent.summarize_history,
    )
    updated_history_record = await conversation_service.get_history_record(conversation)
    try:
        await _record_agent_run(
            session,
            conversation_id=conversation.id,
            trigger_message_id=getattr(updated_history_record, "id", None),
            run_usage=usage,
            latency_ms=latency_ms,
            output_text=agent_result.output,
        )
    except Exception:
        logger.warning("agent_run_record_failed", exc_info=True)


def _compose_user_input_text(message: Message) -> str:
    base_text = message.text or message.caption or ""
    reply_context = _format_reply_context(getattr(message, "reply_to_message", None))
    if reply_context:
        return f"{reply_context}\n{base_text}" if base_text else reply_context
    return base_text


def _compose_media_user_input_text(message: Message, *, kind: str, description: str) -> str:
    sections: list[str] = [f"[{kind.upper()}]"]
    if message.caption:
        sections.append(f"Caption: {message.caption}")
    sections.append(f"Vision: {description}")
    payload = "\n".join(sections)
    reply_context = _format_reply_context(getattr(message, "reply_to_message", None))
    if reply_context:
        return f"{reply_context}\n{payload}"
    return payload


def _format_reply_context(reply_message: Message | None) -> str:
    if reply_message is None:
        return ""
    reply_text = reply_message.text or reply_message.caption or ""
    reply_text = _sanitize_reply_text(reply_text)
    if not reply_text:
        return ""
    reply_author = reply_message.from_user
    role = "Assistant" if getattr(reply_author, "is_bot", False) else "User"
    safe_text = reply_text.replace('"', '\\"')
    return f'> Quote from {role}: "{safe_text}"'


def _sanitize_reply_text(text: str | None) -> str:
    if not text:
        return ""
    compact = " ".join(text.split())
    if len(compact) <= REPLY_CONTEXT_CHAR_LIMIT:
        return compact
    return f"{compact[: REPLY_CONTEXT_CHAR_LIMIT].rstrip()}..."


async def _send_typing_action(message: Message) -> None:
    try:
        while True:
            await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


async def _record_agent_run(
    session: AsyncSession,
    *,
    conversation_id: int,
    trigger_message_id: int | None,
    run_usage: RunUsage | None,
    latency_ms: int,
    output_text: str | None,
) -> None:
    # AgentRun persistence temporarily disabled; keep placeholder for future logging.
    return None


def _truncate_result_summary(text: str | None) -> str | None:
    if not text:
        return None
    trimmed = text.strip()
    if not trimmed:
        return None
    if len(trimmed) <= RESULT_SUMMARY_CHAR_LIMIT:
        return trimmed
    return f"{trimmed[: RESULT_SUMMARY_CHAR_LIMIT].rstrip()}..."


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
    await answer_with_retry(message, reply_text, parse_mode=None)


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
async def handle_photo(
    message: Message,
    session: AsyncSession,
    agent: AgentOrchestrator,
    media_caption_service: MediaCaptionService | None = None,
    db_user: User | None = None,
) -> None:
    if db_user is None:
        return
    if media_caption_service is None:
        await _handle_non_text(message, session, db_user, kind="photo")
        return
    try:
        description = await media_caption_service.describe_photo(message)
    except MediaCaptionError as exc:
        logger.info("media_caption_failed", kind="photo", error=str(exc))
        await _handle_non_text(message, session, db_user, kind="photo")
        return
    user_text = _compose_media_user_input_text(message, kind="photo", description=description)
    await _process_user_prompt(
        message,
        session=session,
        agent=agent,
        db_user=db_user,
        user_text=user_text,
    )


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
async def handle_sticker(
    message: Message,
    session: AsyncSession,
    agent: AgentOrchestrator,
    media_caption_service: MediaCaptionService | None = None,
    db_user: User | None = None,
) -> None:
    if db_user is None:
        return
    if media_caption_service is None:
        await _handle_non_text(message, session, db_user, kind="sticker")
        return
    try:
        description = await media_caption_service.describe_sticker(message)
    except MediaCaptionError as exc:
        logger.info("media_caption_failed", kind="sticker", error=str(exc))
        await _handle_non_text(message, session, db_user, kind="sticker")
        return
    user_text = _compose_media_user_input_text(message, kind="sticker", description=description)
    await _process_user_prompt(
        message,
        session=session,
        agent=agent,
        db_user=db_user,
        user_text=user_text,
    )


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
