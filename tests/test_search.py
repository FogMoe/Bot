"""Tests for the placeholder search service/tool."""

from __future__ import annotations

import pytest
import httpx

from app.services.search import SearchService


@pytest.mark.asyncio
async def test_search_returns_placeholder_result():
    async with httpx.AsyncClient() as client:
        service = SearchService(client)
        results = await service.search("python testing")
    assert results == ["Search result placeholder for: python testing"]


@pytest.mark.asyncio
async def test_search_ignores_empty_query():
    async with httpx.AsyncClient() as client:
        service = SearchService(client)
        results = await service.search("   ")
    assert results == []
