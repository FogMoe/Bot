"""Conversation persistence helpers."""

from __future__ import annotations

from datetime import datetime

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

    async def add_message(
        self,
        conversation: Conversation,
        *,
        user: User | None,
        role: str,
        content_markdown: str | None,
        content_plain: str | None,
        token_count: int | None = None,
        reply_to: Message | None = None,
        delivered_fragment_index: int | None = None,
        visible: bool = True,
    ) -> Message:
        message = Message(
            conversation_id=conversation.id,
            user_id=user.id if user else None,
            role=role,
            content_markdown=content_markdown,
            content_plain=content_plain,
            reply_to_message_id=reply_to.id if reply_to else None,
            token_count=token_count,
            delivered_fragment_index=delivered_fragment_index,
            is_visible_to_user=visible,
        )
        self.session.add(message)
        conversation.last_interaction_at = datetime.utcnow()
        if token_count:
            conversation.context_tokens += token_count
        await self.session.flush()
        return message

    async def get_recent_messages(
        self, conversation: Conversation, limit: int = 20
    ) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.sent_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(reversed(result.scalars().all()))
