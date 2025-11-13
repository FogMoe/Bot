"""Tests for the search + external tool service layer."""

from __future__ import annotations

import json

import pytest
import httpx
from pydantic import SecretStr

from app.config import ExternalToolSettings
from app.services.external_tools import (
    CodeExecutionService,
    SearchService,
    ToolServiceError,
    WebContentService,
)


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


@pytest.mark.asyncio
async def test_google_search_requires_api_key():
    async with httpx.AsyncClient() as client:
        service = SearchService(client, settings=ExternalToolSettings())
        with pytest.raises(ToolServiceError):
            await service.google_search("python")


@pytest.mark.asyncio
async def test_google_search_success(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        assert request.url.params["api_key"] == "secret"
        assert request.url.params["q"] == "python testing"
        return httpx.Response(
            200,
            json={
                "search_metadata": {"id": "123"},
                "search_parameters": {"q": "python testing"},
                "organic_results": [{"title": "Result"}],
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        settings = ExternalToolSettings(serpapi_api_key=SecretStr("secret"))
        service = SearchService(client, settings=settings)
        payload = await service.google_search("python testing")

    assert payload["search_metadata"] == {"id": "123"}
    assert payload["organic_results"] == [{"title": "Result"}]


@pytest.mark.asyncio
async def test_fetch_url_normalizes_scheme():
    requested: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, text="body", headers={"Content-Type": "text/plain"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        service = WebContentService(client, settings=ExternalToolSettings())
        payload = await service.fetch("example.com/path")

    assert requested == ["https://r.jina.ai/https://example.com/path"]
    assert payload["status_code"] == 200
    assert payload["content"] == "body"


@pytest.mark.asyncio
async def test_fetch_url_with_fragment_uses_post():
    methods: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        assert request.url == httpx.URL("https://r.jina.ai/")
        assert b"url=https%3A%2F%2Fexample.com%2F%23section" in request.content
        return httpx.Response(200, text="body")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        service = WebContentService(client, settings=ExternalToolSettings())
        await service.fetch("example.com/#section")

    assert methods == ["POST"]


@pytest.mark.asyncio
async def test_execute_python_code_requires_url():
    async with httpx.AsyncClient() as client:
        service = CodeExecutionService(client, settings=ExternalToolSettings())
        with pytest.raises(ToolServiceError):
            await service.execute("print('hi')")


@pytest.mark.asyncio
async def test_execute_python_code_success():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Auth-Token"] == "jk"
        assert request.url == httpx.URL(
            "https://judge0.example/api/submissions?base64_encoded=true&wait=true"
        )
        body = json.loads(request.content.decode("utf-8"))
        assert body["language_id"] == 99
        return httpx.Response(
            200,
            json={
                "token": "abc",
                "status": {"id": 3, "description": "Accepted"},
                "stdout": "b2s=",
                "stderr": None,
                "compile_output": None,
                "message": None,
                "time": "0.1",
                "memory": 1024,
            },
        )

    transport = httpx.MockTransport(handler)
    settings = ExternalToolSettings(
        judge0_api_url="https://judge0.example/api",
        judge0_api_key=SecretStr("jk"),
        judge0_language_id=99,
    )
    async with httpx.AsyncClient(transport=transport) as client:
        service = CodeExecutionService(client, settings=settings)
        payload = await service.execute("print('ok')")

    assert payload["stdout"] == "ok"
    assert payload["stderr"] == ""
    assert payload["status_description"] == "Accepted"
