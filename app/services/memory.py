"""Long-term memory helpers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.core import LongTermMemory, MemoryChunk, Message


class MemoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def fetch_relevant_memories(
        self, user_id: int, *, limit: int = 5
    ) -> list[LongTermMemory]:
        stmt = (
            select(LongTermMemory)
            .where(LongTermMemory.user_id == user_id, LongTermMemory.is_active.is_(True))
            .order_by(LongTermMemory.updated_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create_memory(
        self,
        *,
        user_id: int,
        conversation_id: int | None,
        source_message: Message | None,
        content: str,
        memory_type: str = "fact",
    ) -> LongTermMemory:
        memory = LongTermMemory(
            user_id=user_id,
            conversation_id=conversation_id,
            source_message_id=source_message.id if source_message else None,
            content=content,
            memory_type=memory_type,
        )
        self.session.add(memory)
        await self.session.flush()
        return memory

    async def flag_chunk_for_compression(
        self, conversation_id: int, *, start: Message, end: Message, token_count: int
    ) -> MemoryChunk:
        chunk = MemoryChunk(
            conversation_id=conversation_id,
            start_message_id=start.id,
            end_message_id=end.id,
            token_count=token_count,
            state="needs_compress",
        )
        self.session.add(chunk)
        await self.session.flush()
        return chunk
