"""Conversation persistence helpers."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Awaitable, Callable, Sequence

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.run import AgentRunResult
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.core import Conversation, ConversationArchive, Message, User
from app.utils.tokens import estimate_tokens

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

        conversation = Conversation(
            user_id=user.id,
            title=f"Chat {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
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
        usage = agent_result.usage()
        previous_tokens = history_record.total_tokens if history_record else 0
        aggregate_tokens = (previous_tokens or 0) + usage.total_tokens

        if aggregate_tokens >= ARCHIVE_TOKEN_THRESHOLD:
            summary_text = await summarizer(messages)
            await self._upsert_archive(
                conversation,
                user=user,
                messages=messages,
                summary_text=summary_text,
                token_count=aggregate_tokens,
            )
            trimmed = list(messages[-RECENT_MESSAGE_LIMIT :])
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
                token_count=aggregate_tokens,
            )

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

        conversation.last_interaction_at = datetime.utcnow()
        conversation.context_tokens = token_count

        await self.session.flush()

    def _estimate_tokens(self, messages: Sequence[ModelMessage]) -> int:
        buffer: list[str] = []
        for message in messages:
            if isinstance(message, ModelRequest):
                for part in message.parts:
                    if isinstance(part, UserPromptPart):
                        buffer.append(str(part.content))
            elif isinstance(message, ModelResponse):
                buffer.extend(part.content for part in message.parts if isinstance(part, TextPart))
        transcript = "\n".join(buffer)
        return estimate_tokens(transcript) if transcript else 0
