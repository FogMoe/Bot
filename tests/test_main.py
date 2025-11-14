"""Tests for logging configuration and async main bootstrap."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import structlog

from app import main as main_module
from app.logging import configure_logging


def test_configure_logging_outputs_json(capsys):
    configure_logging()
    logger = structlog.get_logger()
    logger.info("unit-test", foo="bar")
    out = capsys.readouterr().out
    assert "unit-test" in out
    assert "foo" in out


class DummyToken:
    def __init__(self, value: str) -> None:
        self.value = value

    def get_secret_value(self) -> str:
        return self.value


class DummyLLM:
    def __init__(self) -> None:
        self.applied = False

    def apply_environment(self) -> None:
        self.applied = True


class DummyDispatcher:
    def __init__(self) -> None:
        self.included = []
        self.outer_middlewares = []
        self.message_middlewares = []
        self.started = False
        self.update = SimpleNamespace(outer_middleware=self.outer_middlewares.append)
        self.message = SimpleNamespace(middleware=self.message_middlewares.append)
        self.registered_error_handlers = []
        self.errors = SimpleNamespace(register=self.register_error)

    def include_router(self, router):
        self.included.append(router)

    def register_error(self, handler):
        self.registered_error_handlers.append(handler)

    async def start_polling(self, bot, **kwargs):
        self.started = True
        self.bot = bot
        self.start_kwargs = kwargs


class DummyDatabase:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.session_calls = 0

    @asynccontextmanager
    async def session(self):
        self.session_calls += 1
        yield SimpleNamespace()


class DummyAgent:
    def __init__(self, settings) -> None:
        self.settings = settings


@pytest.mark.asyncio
async def test_main_bootstrap(monkeypatch):
    dummy_llm = DummyLLM()
    settings = SimpleNamespace(
        llm=dummy_llm,
        telegram_proxy=None,
        telegram_token=DummyToken("token"),
        enable_markdown_v2=True,
        environment="test",
        default_language="en",
        request_limit=SimpleNamespace(interval_seconds=1, max_requests=1, window_retention_hours=24),
        vision=None,
        database=SimpleNamespace(
            dsn="sqlite://",
            echo=False,
            pool_size=5,
            max_overflow=10,
            pool_recycle=3600,
            pool_pre_ping=True,
        ),
    )

    middleware_inits = {}

    def _capture(name):
        def factory(*args, **kwargs):
            middleware_inits[name] = (args, kwargs)
            return f"{name}-instance"

        return factory

    dummy_dispatcher = DummyDispatcher()
    dummy_database = DummyDatabase(settings)
    seed_calls = {}

    async def fake_ensure(session, ensure_settings):
        seed_calls["called"] = (session, ensure_settings)

    monkeypatch.setattr(main_module, "configure_logging", lambda: None)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "Bot", lambda *args, **kwargs: SimpleNamespace())
    monkeypatch.setattr(main_module, "Dispatcher", lambda: dummy_dispatcher)
    monkeypatch.setattr(main_module, "Database", lambda settings: dummy_database)
    monkeypatch.setattr(main_module, "ensure_subscription_plans", fake_ensure)
    monkeypatch.setattr(main_module, "AgentOrchestrator", DummyAgent)
    dummy_media_service = object()
    monkeypatch.setattr(main_module, "MediaCaptionService", lambda settings: dummy_media_service)
    monkeypatch.setattr(main_module, "DbSessionMiddleware", _capture("db"))
    monkeypatch.setattr(main_module, "ThrottleMiddleware", _capture("throttle"))
    monkeypatch.setattr(main_module, "UserContextMiddleware", lambda: "userctx")
    monkeypatch.setattr(main_module, "RateLimitMiddleware", _capture("rate"))
    dummy_monitor = object()
    monkeypatch.setattr(main_module, "ErrorMonitor", lambda settings: dummy_monitor)
    monkeypatch.setattr(main_module, "setup_routers", lambda: "router")

    await main_module.main()

    assert dummy_llm.applied is True
    assert dummy_database.session_calls == 1
    assert "called" in seed_calls
    assert dummy_dispatcher.started is True
    assert dummy_dispatcher.included == ["router"]
    assert dummy_dispatcher.registered_error_handlers == [dummy_monitor]
    assert middleware_inits["db"][0][0] is dummy_database
    assert middleware_inits["throttle"][0][0] is settings
    assert middleware_inits["rate"][0][0] is settings
