"""Search-related business logic (placeholder implementation)."""

from __future__ import annotations

from typing import Sequence

import httpx


class SearchService:
    """Encapsulates search provider integration.

    Replace the placeholder implementation with actual API calls, caching, etc.
    """

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client

    async def search(self, query: str) -> Sequence[str]:
        query = query.strip()
        if not query:
            return []
        # TODO: integrate real provider; for now just echo the query.
        return [f"Search result placeholder for: {query}"]


__all__ = ["SearchService"]
