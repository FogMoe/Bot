"""Unit tests for the summary agent configuration/overrides."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from app.agents.summary import SummaryAgent
from app.config import (
    AzureProviderSettings,
    BotSettings,
    LLMSettings,
    OpenAICompatibleSettings,
    SummaryModelSettings,
)
from pydantic_ai.models.openai import OpenAIChatModel


def _base_settings(**kwargs) -> BotSettings:
    defaults = {
        "telegram_token": SecretStr("123:ABC"),
    }
    defaults.update(kwargs)
    return BotSettings(**defaults)


def test_summary_agent_uses_override_model_name():
    settings = _base_settings(
        llm=LLMSettings(
            provider="openai",
            model="gpt-4o-mini",
            openai=OpenAICompatibleSettings(api_key=SecretStr("sk-test")),
        ),
        summary=SummaryModelSettings(provider="openai", model="gpt-4o-mini-1"),
    )
    agent = SummaryAgent.build(settings)
    assert isinstance(agent.agent.model, OpenAIChatModel)
    assert agent.agent.model.model_name == "gpt-4o-mini-1"


def test_summary_agent_requires_azure_fields_when_override_only_sets_provider():
    settings = _base_settings(
        llm=LLMSettings(provider="openai", model="gpt-4o-mini"),
        summary=SummaryModelSettings(provider="azure"),
    )
    with pytest.raises(ValueError):
        SummaryAgent.build(settings)


def test_summary_agent_accepts_full_azure_override():
    settings = _base_settings(
        llm=LLMSettings(
            provider="openai",
            model="gpt-4o-mini",
            azure=AzureProviderSettings(
                api_key=SecretStr("azure-key"),
                base_url="https://summary.azure.example/v1",
                api_version="2024-12-01-preview",
            ),
        ),
        summary=SummaryModelSettings(provider="azure", model="gpt-4o-mini"),
    )
    agent = SummaryAgent.build(settings)
    assert isinstance(agent.agent.model, OpenAIChatModel)
