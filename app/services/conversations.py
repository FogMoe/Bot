"""Conversation persistence helpers."""

from __future__ import annotations

import json
from typing import Awaitable, Callable, Sequence

from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    SystemPromptPart,
    UserPromptPart,
)
from pydantic_ai.run import AgentRunResult
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.core import Conversation, ConversationArchive, Message, User
from app.utils.tokens import estimate_tokens
from app.utils.datetime import utc_now

ARCHIVE_TOKEN_THRESHOLD = 100_000
RECENT_MESSAGE_LIMIT = 20


class ConversationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create_active_conversation(self, user: User) -> Conversation:
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user.id, Conversation.status == "active")
            .order_by(Conversation.updated_at.desc())
        )
        result = await self.session.execute(stmt)
        conversation = result.scalar_one_or_none()
        if conversation:
            return conversation
        return await self.create_conversation(user)

    async def create_conversation(self, user: User) -> Conversation:
        conversation = Conversation(
            user_id=user.id,
            title=f"Chat {utc_now().strftime('%Y-%m-%d %H:%M')}",
            context_tokens=0,
            status="active",
        )
        self.session.add(conversation)
        await self.session.flush()
        return conversation

    async def get_history_record(self, conversation: Conversation) -> Message | None:
        stmt = select(Message).where(Message.conversation_id == conversation.id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    def deserialize_history(self, record: Message | None) -> list[ModelMessage]:
        if not record or not record.history:
            return []
        return ModelMessagesTypeAdapter.validate_python(record.history)

    async def get_prior_summary(self, conversation: Conversation) -> str | None:
        stmt = select(ConversationArchive.summary_text).where(
            ConversationArchive.conversation_id == conversation.id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def process_agent_result(
        self,
        conversation: Conversation,
        *,
        user: User,
        agent_result: AgentRunResult[str],
        history_record: Message | None,
        summarizer: Callable[[Sequence[ModelMessage]], Awaitable[str]],
    ) -> None:
        messages = agent_result.all_messages()
        current_tokens = self._estimate_tokens(messages)

        if current_tokens >= ARCHIVE_TOKEN_THRESHOLD:
            summary_text = await summarizer(messages)
            await self._upsert_archive(
                conversation,
                user=user,
                messages=messages,
                summary_text=summary_text,
                token_count=current_tokens,
            )
            trimmed = self._recent_messages_with_tool_context(messages, RECENT_MESSAGE_LIMIT)
            trimmed_tokens = self._estimate_tokens(trimmed)
            await self._persist_history(
                conversation,
                user=user,
                messages=trimmed,
                token_count=trimmed_tokens,
            )
        else:
            await self._persist_history(
                conversation,
                user=user,
                messages=messages,
                token_count=current_tokens,
            )

    async def archive_full_history(
        self,
        conversation: Conversation,
        *,
        user: User,
        messages: Sequence[ModelMessage],
        summary_text: str,
    ) -> None:
        token_count = self._estimate_tokens(messages)
        await self._upsert_archive(
            conversation,
            user=user,
            messages=messages,
            summary_text=summary_text,
            token_count=token_count,
        )

    async def mark_conversation_archived(self, conversation: Conversation) -> None:
        conversation.status = "archived"
        conversation.last_interaction_at = utc_now()
        await self.session.flush()

    async def delete_history(self, conversation: Conversation) -> None:
        await self.session.execute(
            delete(Message).where(Message.conversation_id == conversation.id)
        )
        await self.session.flush()

    async def store_manual_history(
        self,
        conversation: Conversation,
        *,
        user: User,
        messages: Sequence[ModelMessage],
    ) -> None:
        token_count = self._estimate_tokens(messages)
        await self._persist_history(
            conversation,
            user=user,
            messages=list(messages),
            token_count=token_count,
        )

    async def _upsert_archive(
        self,
        conversation: Conversation,
        *,
        user: User,
        messages: Sequence[ModelMessage],
        summary_text: str,
        token_count: int,
    ) -> None:
        payload_json = ModelMessagesTypeAdapter.dump_json(list(messages))
        payload = json.loads(payload_json)

        stmt = select(ConversationArchive).where(
            ConversationArchive.conversation_id == conversation.id
        )
        result = await self.session.execute(stmt)
        archive = result.scalar_one_or_none()
        if archive is None:
            archive = ConversationArchive(
                conversation_id=conversation.id,
                user_id=user.id,
                summary_text=summary_text,
                history=payload,
                token_count=token_count,
            )
            self.session.add(archive)
        else:
            archive.summary_text = summary_text
            archive.history = payload
            archive.token_count = token_count
            archive.user_id = user.id

    async def _persist_history(
        self,
        conversation: Conversation,
        *,
        user: User,
        messages: Sequence[ModelMessage],
        token_count: int,
    ) -> None:
        payload_json = ModelMessagesTypeAdapter.dump_json(list(messages))
        payload = json.loads(payload_json)
        message_count = len(messages)

        stmt = select(Message).where(Message.conversation_id == conversation.id)
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            record = Message(
                conversation_id=conversation.id,
                user_id=user.id,
                history=payload,
                total_tokens=token_count,
                message_count=message_count,
            )
            self.session.add(record)
        else:
            record.history = payload
            record.user_id = user.id
            record.total_tokens = token_count
            record.message_count = message_count

        conversation.last_interaction_at = utc_now()
        conversation.context_tokens = token_count

        await self.session.flush()

    def _estimate_tokens(self, messages: Sequence[ModelMessage]) -> int:
        buffer: list[str] = []
        for message in messages:
            if isinstance(message, ModelRequest):
                for part in message.parts:
                    if isinstance(part, UserPromptPart):
                        buffer.append(str(part.content))
                    elif isinstance(part, SystemPromptPart):
                        buffer.append(f"SYSTEM_PROMPT: {str(part.content)}")
                    elif isinstance(part, ToolReturnPart):
                        buffer.append(
                            f"TOOL_RETURN[{part.tool_name}]: {_stringify_tool_content(part.content)}"
                        )
            elif isinstance(message, ModelResponse):
                for part in message.parts:
                    if isinstance(part, TextPart):
                        buffer.append(part.content)
                    elif isinstance(part, ToolCallPart):
                        buffer.append(
                            f"TOOL_CALL[{part.tool_name}]: {_stringify_tool_content(part.args)}"
                        )
        transcript = "\n".join(buffer)
        return estimate_tokens(transcript) if transcript else 0

    def _recent_messages_with_tool_context(
        self, messages: Sequence[ModelMessage], limit: int
    ) -> list[ModelMessage]:
        if len(messages) <= limit:
            return list(messages)

        start = len(messages) - limit
        while start > 0 and _requires_preceding_tool_call(messages[start]):
            start -= 1
        return list(messages[start:])


def _requires_preceding_tool_call(message: ModelMessage) -> bool:
    if isinstance(message, ModelRequest):
        return any(isinstance(part, ToolReturnPart) for part in message.parts)
    return False


def _stringify_tool_content(payload: object) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, ensure_ascii=False)
    except TypeError:
        return str(payload)
