"""Conversation persistence helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
from pydantic_ai.usage import RunUsage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.core import Conversation, Message, User


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

    async def load_history(self, conversation: Conversation) -> list[ModelMessage]:
        stmt = select(Message).where(Message.conversation_id == conversation.id)
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        if not record or not record.history:
            return []
        return ModelMessagesTypeAdapter.validate_python(record.history)

    async def save_history(
        self,
        conversation: Conversation,
        *,
        user: User,
        messages: Sequence[ModelMessage],
        usage: RunUsage | None = None,
    ) -> Message:
        payload = ModelMessagesTypeAdapter.dump_python(list(messages))
        message_count = len(payload)

        stmt = select(Message).where(Message.conversation_id == conversation.id)
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            record = Message(
                conversation_id=conversation.id,
                user_id=user.id,
                history=payload,
                total_tokens=usage.total_tokens if usage else None,
                message_count=message_count,
            )
            self.session.add(record)
        else:
            record.history = payload
            record.user_id = user.id
            record.total_tokens = usage.total_tokens if usage else record.total_tokens
            record.message_count = message_count

        conversation.last_interaction_at = datetime.utcnow()
        if usage:
            conversation.context_tokens = usage.total_tokens

        await self.session.flush()
        return record
