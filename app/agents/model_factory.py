"""Helpers for building provider-specific model specs."""

from __future__ import annotations

from typing import Literal

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.azure import AzureProvider
from pydantic_ai.providers.openai import OpenAIProvider

from app.config import LLMSettings


ProviderLiteral = Literal["openai", "azure", "azure_openai", "zhipu", "gemini", "custom", "anthropic"]


def build_model_spec(provider: str, model_name: str, llm_settings: LLMSettings) -> str | OpenAIChatModel:
    provider_key = provider.lower()
    if provider_key in {"azure", "azure_openai"}:
        api_key = llm_settings.azure.api_key or llm_settings.api_key
        base_url = llm_settings.azure.base_url or llm_settings.base_url
        api_version = llm_settings.azure.api_version or llm_settings.api_version
        if not (api_key and base_url and api_version):
            raise ValueError(
                "Azure OpenAI requires BOT_LLM__AZURE__API_KEY, BOT_LLM__AZURE__BASE_URL, and BOT_LLM__AZURE__API_VERSION."
            )
        azure_provider = AzureProvider(
            azure_endpoint=str(base_url),
            api_version=api_version,
            api_key=api_key.get_secret_value(),
        )
        return OpenAIChatModel(model_name, provider=azure_provider)

    if provider_key in {"openai", "custom", "zhipu", "gemini"}:
        api_key, base_url = llm_settings.openai_like_credentials(provider_key)
        if provider_key in {"zhipu", "gemini"} and (api_key is None or base_url is None):
            raise ValueError(
                f"Provider '{provider}' requires API key and base URL. Configure BOT_LLM__{provider.upper()}__* values."
            )
        openai_provider = OpenAIProvider(
            api_key=api_key.get_secret_value() if api_key else None,
            base_url=base_url,
        )
        return OpenAIChatModel(model_name, provider=openai_provider)

    if provider_key == "anthropic":
        return f"anthropic:{model_name}"

    return f"{provider}:{model_name}"


__all__ = ["build_model_spec"]
