from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.agents import tool_logging


class SampleModel(BaseModel):
    value: int


@dataclass
class SampleData:
    name: str


def test_should_log_tool_call_prefers_env(monkeypatch):
    monkeypatch.setenv("BOT_ENVIRONMENT", "dev")
    assert tool_logging.should_log_tool_call(None) is True

    monkeypatch.setenv("BOT_ENVIRONMENT", "prod")
    assert tool_logging.should_log_tool_call(None) is False


def test_should_log_tool_call_falls_back_to_ctx(monkeypatch):
    monkeypatch.delenv("BOT_ENVIRONMENT", raising=False)
    ctx = SimpleNamespace(deps=SimpleNamespace(environment="dev"))
    assert tool_logging.should_log_tool_call(ctx) is True

    ctx.deps.environment = "prod"
    assert tool_logging.should_log_tool_call(ctx) is False


def test_extract_ctx_and_arguments_with_ctx_first():
    ctx = object()
    payload = SampleModel(value=5)
    args = (ctx, payload)

    assert tool_logging.extract_ctx(args, {}, takes_ctx=True) is ctx
    extracted = tool_logging.extract_tool_arguments(args, {}, takes_ctx=True)
    assert extracted is payload


def test_extract_arguments_from_kwargs():
    ctx = object()
    payload = SampleModel(value=10)
    kwargs = {"ctx": ctx, "data": payload}

    assert tool_logging.extract_ctx((), kwargs, takes_ctx=True) is ctx
    assert tool_logging.extract_tool_arguments((), kwargs, takes_ctx=True) is payload


@pytest.mark.parametrize(
    "value, expected",
    [
        (SampleModel(value=1), {"value": 1}),
        (SampleData(name="foo"), {"name": "foo"}),
        ({"inner": SampleModel(value=2)}, {"inner": {"value": 2}}),
        ([SampleModel(value=3)], [{"value": 3}]),
        ("text", "text"),
    ],
)
def test_serialize_tool_payload(value, expected):
    assert tool_logging.serialize_tool_payload(value) == expected
