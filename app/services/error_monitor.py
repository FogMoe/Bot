"""Notify the administrator about unhandled bot errors."""

from __future__ import annotations

import json
import traceback
from typing import Any

from aiogram import Bot
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import Chat, ErrorEvent, Update, User

from app.bot.utils.telegram import bot_send_with_retry
from app.config import BotSettings
from app.logging import logger

# Telegram messages are limited to 4096 characters.
TELEGRAM_MESSAGE_LIMIT = 3900
TRACEBACK_CHAR_LIMIT = 1800
PAYLOAD_CHAR_LIMIT = 1200


class ErrorMonitor:
    """Async callable plugged into aiogram error observer."""

    def __init__(self, settings: BotSettings) -> None:
        self._settings = settings

    async def handle_error(self, event: ErrorEvent, bot: Bot):
        """Send error summary to the configured admin chat."""

        admin_id = self._settings.admin_telegram_id
        if admin_id is None:
            return UNHANDLED

        message = self._build_message(event)
        if not message:
            return UNHANDLED

        logger.error(
            "bot_error_captured",
            exception_type=event.exception.__class__.__name__,
            exception=str(event.exception),
            update_id=getattr(event.update, "update_id", None),
        )
        try:
            await bot_send_with_retry(bot, chat_id=admin_id, text=message, parse_mode=None)
        except Exception:
            logger.exception(
                "error_monitor_notification_failed",
                update_id=getattr(event.update, "update_id", None),
            )
        return UNHANDLED

    def _build_message(self, event: ErrorEvent) -> str:
        update = event.update
        exception = event.exception
        update_type, payload_preview = self._describe_update(update)
        user_summary, chat_summary = self._describe_actor(update)
        traceback_text = self._format_traceback(exception)

        lines = [
            "BOT ERROR DETECTED",
            f"Environment: {self._settings.environment}",
            f"Exception: {exception.__class__.__name__}: {exception}",
            f"Update ID: {getattr(update, 'update_id', 'unknown')}",
            f"Update Type: {update_type}",
            f"User: {user_summary}",
            f"Chat: {chat_summary}",
        ]
        if traceback_text:
            lines.extend(["", "Traceback:", traceback_text])
        if payload_preview:
            lines.extend(["", "Payload:", payload_preview])

        text = "\n".join(lines).strip()
        if len(text) > TELEGRAM_MESSAGE_LIMIT:
            text = f"{text[:TELEGRAM_MESSAGE_LIMIT - 15].rstrip()}\n...[truncated]"
        return text

    def _describe_update(self, update: Update | None) -> tuple[str, str]:
        if update is None:
            return "unknown", ""

        update_dict = update.model_dump(exclude_unset=True, exclude_none=True)
        update_dict.pop("update_id", None)
        for key, value in update_dict.items():
            if value not in (None, {}, [], ()):
                payload_text = self._pretty_json(value)
                return key, payload_text
        return "unknown", ""

    def _describe_actor(self, update: Update | None) -> tuple[str, str]:
        if update is None:
            return "unknown", "unknown"

        actor_source = self._locate_actor_source(update)
        user = None
        chat = None
        if actor_source is not None:
            user = getattr(actor_source, "from_user", None) or getattr(actor_source, "user", None)
            chat = getattr(actor_source, "chat", None)

        return self._format_user(user), self._format_chat(chat)

    def _locate_actor_source(self, update: Update) -> Any | None:
        possible_fields = (
            "message",
            "edited_message",
            "channel_post",
            "edited_channel_post",
            "business_message",
            "edited_business_message",
            "callback_query",
            "inline_query",
            "chosen_inline_result",
            "shipping_query",
            "pre_checkout_query",
            "poll_answer",
            "my_chat_member",
            "chat_member",
            "chat_join_request",
            "message_reaction",
            "message_reaction_count",
        )
        for field in possible_fields:
            value = getattr(update, field, None)
            if value is not None:
                return value
        return None

    def _format_user(self, user: User | None) -> str:
        if user is None:
            return "unknown"
        segments = [str(user.id)]
        full_name = " ".join(part for part in (user.first_name, user.last_name) if part)
        if full_name:
            segments.append(full_name)
        if user.username:
            segments.append(f"@{user.username}")
        return " | ".join(segments)

    def _format_chat(self, chat: Chat | None) -> str:
        if chat is None:
            return "unknown"
        segments = [str(chat.id), chat.type]
        title = chat.title or chat.username or chat.first_name
        if title:
            segments.append(title)
        return " | ".join(segment for segment in segments if segment)

    def _format_traceback(self, exception: Exception) -> str:
        trace = "".join(traceback.format_exception(exception.__class__, exception, exception.__traceback__))
        trace = trace.strip()
        if not trace:
            return ""
        return self._truncate(trace, TRACEBACK_CHAR_LIMIT)

    def _pretty_json(self, payload: Any) -> str:
        try:
            serialized = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        except TypeError:
            serialized = str(payload)
        return self._truncate(serialized, PAYLOAD_CHAR_LIMIT)

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        value = value.strip()
        if len(value) <= limit:
            return value
        return f"{value[: limit - 15].rstrip()}\n...[truncated]"


__all__ = ["ErrorMonitor"]
