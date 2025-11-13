"""Services backing agent tools (search, scraping, Judge0 execution)."""

from __future__ import annotations

import base64
from typing import Any, Sequence
from urllib.parse import quote

import httpx

from app.config import ExternalToolSettings


class ToolServiceError(RuntimeError):
    """Raised when an external integration fails or is misconfigured."""


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
        try:
            response = await self._client.get(
                "https://serpapi.com/search",
                params=params,
                timeout=self._settings.request_timeout_seconds,
            )
            response.raise_for_status()
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
        try:
            if "#" in normalized_url:
                response = await self._client.post(
                    self._reader_post_url(),
                    data={"url": normalized_url},
                    timeout=timeout,
                )
            else:
                encoded_url = quote(normalized_url, safe=":/?&=#[]@!$&'()*+,;")
                response = await self._client.get(
                    self._reader_get_url(encoded_url),
                    timeout=timeout,
                )
            response.raise_for_status()
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

        try:
            response = await self._client.post(
                request_url,
                json=payload,
                headers=headers,
                timeout=self._settings.request_timeout_seconds,
            )
            response.raise_for_status()
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


__all__ = [
    "SearchService",
    "WebContentService",
    "CodeExecutionService",
    "ToolServiceError",
]
