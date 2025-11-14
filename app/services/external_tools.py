"""Services backing agent tools (search, scraping, Judge0 execution)."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Sequence, TypeVar
from urllib.parse import quote

import httpx

from app.config import ExternalToolSettings
from app.logging import logger
from app.utils.retry import retry_async


class ToolServiceError(RuntimeError):
    """Raised when an external integration fails or is misconfigured."""


T = TypeVar("T")


@dataclass(slots=True)
class MarketSnapshotResult:
    as_of: str
    items: list[dict[str, Any]]
    total_matches: int
    truncated: bool
    unmatched_tokens: list[str]


class _BaseToolService:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: ExternalToolSettings | None = None,
    ) -> None:
        self._client = http_client
        self._settings = settings or ExternalToolSettings()

    @staticmethod
    def _read_secret(secret: Any) -> str | None:
        if not secret:
            return None
        try:
            return secret.get_secret_value()
        except AttributeError:
            return str(secret)

    async def _retry_http(self, name: str, operation: Callable[[], Awaitable[T]]) -> T:
        return await retry_async(
            operation,
            max_attempts=3,
            base_delay=0.5,
            logger=logger,
            operation_name=name,
        )


class SearchService(_BaseToolService):
    """Encapsulates search provider integration (SerpApi, placeholder web search)."""

    async def search(self, query: str) -> Sequence[str]:
        query = query.strip()
        if not query:
            return []
        return [f"Search result placeholder for: {query}"]

    async def google_search(self, query: str) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise ToolServiceError("Search query must not be empty.")

        api_key = self._read_secret(self._settings.serpapi_api_key)
        if not api_key:
            raise ToolServiceError("SerpApi key is not configured.")

        params = {
            "engine": self._settings.serpapi_engine,
            "q": query,
            "api_key": api_key,
        }
        async def _request():
            response = await self._client.get(
                "https://serpapi.com/search",
                params=params,
                timeout=self._settings.request_timeout_seconds,
            )
            response.raise_for_status()
            return response

        try:
            response = await self._retry_http("serpapi_request", _request)
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500] if exc.response is not None else str(exc)
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            raise ToolServiceError(f"SerpApi request failed ({status_code}): {detail}") from exc
        except httpx.RequestError as exc:
            raise ToolServiceError(f"SerpApi request failed: {exc}") from exc

        data = response.json()
        return {
            "search_metadata": data.get("search_metadata", {}) or {},
            "search_parameters": data.get("search_parameters", {}) or {},
            "organic_results": data.get("organic_results", []) or [],
        }


class WebContentService(_BaseToolService):
    """Fetch and render remote web content via Jina Reader."""

    async def fetch(self, url: str) -> dict[str, Any]:
        normalized_url = (url or "").strip()
        if not normalized_url:
            raise ToolServiceError("Please provide a valid URL.")
        if not normalized_url.startswith(("http://", "https://")):
            normalized_url = f"https://{normalized_url}"

        timeout = self._settings.request_timeout_seconds
        headers = self._reader_headers()
        async def _request():
            if "#" in normalized_url:
                resp = await self._client.post(
                    self._reader_post_url(),
                    data={"url": normalized_url},
                    headers=headers,
                    timeout=timeout,
                )
            else:
                encoded_url = quote(normalized_url, safe=":/?&=#[]@!$&'()*+,;")
                resp = await self._client.get(
                    self._reader_get_url(encoded_url),
                    headers=headers,
                    timeout=timeout,
                )
            resp.raise_for_status()
            return resp

        try:
            response = await self._retry_http("web_content_fetch", _request)
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500] if exc.response is not None else str(exc)
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            raise ToolServiceError(
                f"Upstream fetch failed ({status_code}): {detail}"
            ) from exc
        except httpx.RequestError as exc:
            raise ToolServiceError(f"Failed to fetch URL: {exc}") from exc

        return {
            "url": normalized_url,
            "status_code": response.status_code,
            "content_type": response.headers.get("Content-Type"),
            "content": response.text,
        }

    def _reader_base(self) -> str:
        return str(self._settings.jina_reader_base_url).rstrip("/")

    def _reader_post_url(self) -> str:
        return f"{self._reader_base()}/"

    def _reader_get_url(self, encoded_url: str) -> str:
        return f"{self._reader_base()}/{encoded_url.lstrip('/')}"

    def _reader_headers(self) -> dict[str, str]:
        api_token = self._read_secret(self._settings.jina_reader_api_token)
        if not api_token:
            return {}
        return {"Authorization": f"Bearer {api_token}"}


class CodeExecutionService(_BaseToolService):
    """Execute Python code remotely via Judge0."""

    async def execute(self, source_code: str, stdin: str | None = None) -> dict[str, Any]:
        code = (source_code or "").strip()
        if not code:
            raise ToolServiceError("Source code is required.")

        base_url = self._settings.judge0_api_url
        if not base_url:
            raise ToolServiceError("Judge0 API URL is not configured.")

        request_url = f"{str(base_url).rstrip('/')}/submissions?base64_encoded=true&wait=true"
        headers = {"Content-Type": "application/json"}
        api_key = self._read_secret(self._settings.judge0_api_key)
        if api_key:
            headers["X-Auth-Token"] = api_key

        payload: dict[str, Any] = {
            "language_id": self._settings.judge0_language_id,
            "source_code": _encode_field(code),
        }
        if stdin:
            payload["stdin"] = _encode_field(stdin)

        async def _request():
            resp = await self._client.post(
                request_url,
                json=payload,
                headers=headers,
                timeout=self._settings.request_timeout_seconds,
            )
            resp.raise_for_status()
            return resp

        try:
            response = await self._retry_http("judge0_execute", _request)
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500] if exc.response is not None else str(exc)
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            raise ToolServiceError(f"Submission failed ({status_code}): {detail}") from exc
        except httpx.RequestError as exc:
            raise ToolServiceError(f"Failed to contact Judge0: {exc}") from exc

        result = response.json()
        status_info = result.get("status") or {}
        return {
            "token": result.get("token"),
            "status_id": status_info.get("id"),
            "status_description": status_info.get("description"),
            "stdout": _decode_field(result.get("stdout")),
            "stderr": _decode_field(result.get("stderr")),
            "compile_output": _decode_field(result.get("compile_output")),
            "message": result.get("message"),
            "time": result.get("time"),
            "memory": result.get("memory"),
        }


def _encode_field(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _decode_field(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return base64.b64decode(value).decode("utf-8", errors="replace")
    except Exception:
        return str(value)


class MarketDataService(_BaseToolService):
    """Fetch and filter real-time market snapshot data."""

    SYMBOL_EXACT_SCORE = 3
    SYMBOL_PARTIAL_SCORE = 2
    NAME_PARTIAL_SCORE = 1

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: ExternalToolSettings | None = None,
    ) -> None:
        super().__init__(http_client, settings=settings)
        limit = self._settings.market_snapshot_max_results
        self._default_limit = max(1, min(limit, 5))

    async def query_snapshots(
        self, tokens: Sequence[str], limit: int | None = None
    ) -> MarketSnapshotResult:
        normalized_tokens = [token.strip() for token in tokens if token and token.strip()]
        if not normalized_tokens:
            raise ToolServiceError("Please specify at least one search keyword.")

        payload = await self._fetch_snapshot_payload()
        if not isinstance(payload, dict) or not payload:
            raise ToolServiceError("Market data provider returned no data.")

        records = [self._normalize_record(symbol, info) for symbol, info in payload.items()]
        matches, matched_token_set = self._filter_records(records, normalized_tokens)
        unmatched = [token for token in normalized_tokens if token not in matched_token_set]

        limit_value = self._normalize_limit(limit)
        total_matches = len(matches)
        truncated = total_matches > limit_value
        limited_items = matches[:limit_value]

        as_of_iso = self._compute_as_of(records)

        return MarketSnapshotResult(
            as_of=as_of_iso,
            items=limited_items,
            total_matches=total_matches,
            truncated=truncated,
            unmatched_tokens=unmatched,
        )

    async def _fetch_snapshot_payload(self) -> dict[str, Any]:
        base_url = str(self._settings.market_snapshot_url).rstrip("/")
        secret_key = self._read_secret(self._settings.market_snapshot_secret_key)
        if not secret_key:
            raise ToolServiceError("Market snapshot secret key is not configured.")

        params = {
            "action": self._settings.market_snapshot_action,
            "secretkey": secret_key,
        }

        async def _request():
            response = await self._client.get(
                base_url,
                params=params,
                timeout=self._settings.request_timeout_seconds,
            )
            response.raise_for_status()
            return response

        try:
            response = await self._retry_http("market_snapshot_fetch", _request)
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500] if exc.response is not None else str(exc)
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            raise ToolServiceError(
                f"Market snapshot fetch failed ({status_code}): {detail}"
            ) from exc
        except httpx.RequestError as exc:
            raise ToolServiceError(f"Failed to contact market snapshot provider: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise ToolServiceError("Market snapshot response is not valid JSON.") from exc
        if not isinstance(data, dict):
            raise ToolServiceError("Market snapshot response format is invalid.")
        return data

    def _filter_records(
        self, records: Sequence[dict[str, Any]], tokens: Sequence[str]
    ) -> tuple[list[dict[str, Any]], set[str]]:
        matches: list[dict[str, Any]] = []
        matched_tokens: set[str] = set()
        if not records:
            return matches, matched_tokens

        prepared_tokens = [(token, token.lower()) for token in tokens]

        decorated: list[tuple[int, int, int, dict[str, Any]]] = []
        for record in records:
            symbol = (record.get("symbol") or "").lower()
            name = (record.get("name") or "").lower()
            best_score = 0
            earliest_idx = len(prepared_tokens)
            matched_for_record: list[str] = []
            for idx, (original, lowered) in enumerate(prepared_tokens):
                score = self._match_score(symbol, name, lowered)
                if score:
                    best_score = max(best_score, score)
                    earliest_idx = min(earliest_idx, idx)
                    matched_for_record.append(original)
                    matched_tokens.add(original)
            if matched_for_record:
                record_with_tokens = dict(record)
                record_with_tokens["matched_tokens"] = matched_for_record
                decorated.append(
                    (
                        -best_score,
                        earliest_idx,
                        -int(record_with_tokens.get("collection_timestamp") or 0),
                        record_with_tokens,
                    )
                )

        decorated.sort(key=lambda item: (item[0], item[1], item[2], item[3].get("symbol", "")))
        matches = [item[3] for item in decorated]
        return matches, matched_tokens

    def _match_score(self, symbol: str, name: str, token: str) -> int:
        if not token:
            return 0
        if symbol == token:
            return self.SYMBOL_EXACT_SCORE
        if token in symbol:
            return self.SYMBOL_PARTIAL_SCORE
        if token in name:
            return self.NAME_PARTIAL_SCORE
        return 0

    def _normalize_record(self, symbol: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = dict(payload or {})
        result["symbol"] = str(result.get("symbol") or symbol)
        result["name"] = str(result.get("name") or symbol)
        numeric_fields = (
            "current_price",
            "price_change",
            "percent_change",
            "open_price",
            "high_price",
            "low_price",
            "previous_close_price",
        )
        for field in numeric_fields:
            value = result.get(field)
            if value not in (None, ""):
                result[field] = str(value)
        result["collection_timestamp"] = self._to_int(
            result.get("collection_timestamp") or payload.get("collection_timestamp")
        )
        result["data_provider_timestamp"] = self._to_int(
            result.get("data_provider_timestamp") or payload.get("data_provider_timestamp")
        )
        return result

    @staticmethod
    def _to_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _compute_as_of(self, records: Sequence[dict[str, Any]]) -> str:
        timestamps: list[int] = []
        for record in records:
            raw_ts = record.get("collection_timestamp")
            if isinstance(raw_ts, int):
                timestamps.append(raw_ts)
            else:
                try:
                    timestamps.append(int(raw_ts))
                except (TypeError, ValueError):
                    continue
        if timestamps:
            latest = max(timestamps)
            return datetime.fromtimestamp(latest, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")

    def _normalize_limit(self, requested: int | None) -> int:
        if not requested:
            return self._default_limit
        return max(1, min(requested, self._default_limit))


__all__ = [
    "SearchService",
    "WebContentService",
    "CodeExecutionService",
    "MarketDataService",
    "ToolServiceError",
]
