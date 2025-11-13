from __future__ import annotations

import pytest
import httpx
from pydantic import SecretStr

from app.config import ExternalToolSettings
from app.services.external_tools import SearchService


class DummyResponse:
    def __init__(self):
        self.status_code = 200
        self.text = "{}"
        self.headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "search_metadata": {},
            "search_parameters": {},
            "organic_results": ["ok"],
        }


class FlakyClient:
    def __init__(self):
        self.calls = 0

    async def get(self, *args, **kwargs):
        self.calls += 1
        if self.calls < 3:
            raise httpx.RequestError("boom", request=httpx.Request("GET", "https://serpapi.com/search"))
        return DummyResponse()


@pytest.mark.asyncio
async def test_search_service_retries(monkeypatch):
    async def _noop_sleep(delay):
        return None

    monkeypatch.setattr("app.utils.retry.asyncio.sleep", _noop_sleep)

    settings = ExternalToolSettings(serpapi_api_key=SecretStr("key"))
    client = FlakyClient()
    service = SearchService(client, settings=settings)

    result = await service.google_search("hello")
    assert client.calls == 3
    assert result["organic_results"] == ["ok"]
