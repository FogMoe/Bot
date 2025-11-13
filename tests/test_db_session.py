"""Tests for DbSessionMiddleware behavior."""

from __future__ import annotations

import pytest

from app.bot.middlewares.db_session import DbSessionMiddleware


class DummyDatabase:
    def __init__(self, session):
        self._session = session

    def session(self):
        class _Wrapper:
            def __init__(self, session):
                self.session = session

            async def __aenter__(self):
                return self.session

            async def __aexit__(self, exc_type, exc, tb):
                pass

        return _Wrapper(self._session)


@pytest.mark.asyncio
async def test_db_session_middleware_commits(monkeypatch, session):
    middleware = DbSessionMiddleware(DummyDatabase(session))
    called = {}

    async def handler(event, data):
        assert data["session"] is session
        called["value"] = True
        return "ok"

    result = await middleware(handler, object(), {})
    assert result == "ok"
    assert called


@pytest.mark.asyncio
async def test_db_session_middleware_rolls_back(monkeypatch, session):
    class ExplodingDatabase(DummyDatabase):
        def session(self):
            class _Wrapper:
                def __init__(self, session):
                    self.session = session

                async def __aenter__(self):
                    return self.session

                async def __aexit__(self, exc_type, exc, tb):
                    pass

            return _Wrapper(self._session)

    middleware = DbSessionMiddleware(ExplodingDatabase(session))

    async def handler(event, data):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await middleware(handler, object(), {})
