from __future__ import annotations

from typing import Any

import pytest
import httpx
from pydantic import SecretStr

from app.config import ExternalToolSettings
from app.services.external_tools import MarketDataService, SearchService, ToolServiceError


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


class DummySnapshotClient:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    async def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})

        class _Response:
            status_code = 200
            text = "{}"
            headers = {}

            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        return _Response(self.payload)


@pytest.mark.asyncio
async def test_market_data_service_filters_and_limits():
    payload = {
        "gb_nvda": {
            "symbol": "gb_nvda",
            "name": "NVIDIA",
            "current_price": "1",
            "collection_timestamp": 100,
        },
        "btc_btcbtcusd": {
            "symbol": "btc_btcbtcusd",
            "name": "Bitcoin",
            "current_price": "2",
            "collection_timestamp": 200,
        },
    }
    settings = ExternalToolSettings(market_snapshot_secret_key=SecretStr("secret"))
    client = DummySnapshotClient(payload)
    service = MarketDataService(client, settings=settings)

    result = await service.query_snapshots(["nvda", "btc", "eth"], limit=1)

    assert result.total_matches == 2
    assert result.truncated is True
    assert result.unmatched_tokens == ["eth"]
    assert result.items[0]["symbol"] == "gb_nvda"
    assert result.items[0]["matched_tokens"] == ["nvda"]
    assert client.calls


@pytest.mark.asyncio
async def test_market_data_service_requires_secret():
    settings = ExternalToolSettings()
    client = DummySnapshotClient({})
    service = MarketDataService(client, settings=settings)

    with pytest.raises(ToolServiceError):
        await service.query_snapshots(["btc"], limit=1)
