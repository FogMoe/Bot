from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents import runner as runner_module
from app.config import LLMSettings


class DummySummary:
    async def summarize_history(self, history):
        return "summary"


@pytest.mark.asyncio
async def test_agent_orchestrator_retries_on_failure(monkeypatch, session):
    attempts = {"count": 0}

    class DummyAgent:
        async def run(self, *args, **kwargs):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError("boom")
            return SimpleNamespace(output="done")

    dummy_agent = DummyAgent()
    monkeypatch.setattr(
        runner_module,
        "build_agent",
        lambda settings, tool_registry=None: dummy_agent,
    )
    monkeypatch.setattr(
        runner_module.SummaryAgent,
        "build",
        staticmethod(lambda settings: DummySummary()),
    )
    monkeypatch.setattr(
        runner_module.CollaboratorAgent,
        "build",
        staticmethod(lambda settings: None),
    )

    async def _noop(delay):
        return None

    monkeypatch.setattr("app.utils.retry.asyncio.sleep", _noop)

    settings = SimpleNamespace(
        llm=LLMSettings(provider="openai", model="gpt", request_timeout_seconds=5),
        agent_timeout_seconds=10,
        external_tools=SimpleNamespace(),
        vision=None,
        collaborator=SimpleNamespace(provider=None, model=None),
        environment="test",
    )
    orchestrator = runner_module.AgentOrchestrator(settings=settings)
    result = await orchestrator.run(
        user_id=1,
        conversation_id=1,
        session=session,
        history=[],
        latest_user_message="hi",
        memory_service=SimpleNamespace(),
        prior_summary=None,
        user_profile=None,
    )

    assert attempts["count"] == 3
    assert result.output == "done"
