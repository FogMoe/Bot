"""Insights about users such as impressions and permanent summaries."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.core import ConversationArchive, UserImpression
from app.utils.datetime import utc_now

MAX_IMPRESSION_LENGTH = 500


class UserInsightService:
    """Manage long-lived user insights consumed by agent tools."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_impression(self, user_id: int, impression: str) -> UserImpression:
        """Create or update the stored impression for a user."""

        text = (impression or "").strip()
        if len(text) > MAX_IMPRESSION_LENGTH:
            text = text[:MAX_IMPRESSION_LENGTH]

        stmt = select(UserImpression).where(UserImpression.user_id == user_id)
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        if record:
            record.impression = text
            record.updated_at = utc_now()
        else:
            record = UserImpression(user_id=user_id, impression=text)
            self.session.add(record)

        await self.session.flush()
        return record

    async def fetch_permanent_summaries(
        self,
        user_id: int,
        *,
        start: int,
        end: int,
    ) -> dict[str, Any]:
        """Return a bounded window of conversation summaries for a user."""

        start_idx = max(start, 1)
        end_idx = max(end, start_idx)
        window_size = min(end_idx - start_idx + 1, 10)
        offset = start_idx - 1

        filters = (
            ConversationArchive.user_id == user_id,
            ConversationArchive.summary_text.is_not(None),
            ConversationArchive.summary_text != "",
        )

        count_stmt = select(func.count()).select_from(ConversationArchive).where(*filters)
        total = int((await self.session.execute(count_stmt)).scalar_one() or 0)

        stmt = (
            select(ConversationArchive)
            .where(*filters)
            .order_by(ConversationArchive.created_at.desc(), ConversationArchive.id.desc())
            .offset(offset)
            .limit(window_size)
        )
        rows = (await self.session.execute(stmt)).scalars().all()

        records: list[dict[str, Any]] = []
        for row in rows:
            records.append(
                {
                    "record_id": row.id,
                    "created_at": row.created_at.isoformat(sep=" ") if row.created_at else None,
                    "summary": row.summary_text or "",
                }
            )

        range_end = start_idx + len(records) - 1 if records else start_idx - 1
        return {
            "user_id": user_id,
            "total": total,
            "range_start": start_idx,
            "range_end": range_end,
            "records": records,
        }

    async def get_impression(self, user_id: int) -> str | None:
        stmt = select(UserImpression.impression).where(UserImpression.user_id == user_id)
        result = await self.session.execute(stmt)
        impression = result.scalar_one_or_none()
        if impression:
            return impression
        return None


__all__ = ["UserInsightService", "MAX_IMPRESSION_LENGTH"]
