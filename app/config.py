"""Runtime configuration based on environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
import os

from pydantic import AnyHttpUrl, BaseModel, Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseModel):
    dsn: str = Field(
        default="mysql+asyncmy://bot:bot@localhost:3306/telegram_bot",
        description="SQLAlchemy async DSN using asyncmy driver.",
    )
    pool_size: int = Field(default=5, ge=1, le=50)
    max_overflow: int = Field(default=10, ge=0, le=100)
    echo: bool = False
    pool_recycle: int = Field(default=3600, ge=30)
    pool_pre_ping: bool = Field(default=True)


class RedisSettings(BaseModel):
    url: str | None = Field(default=None, description="Redis URL kept for future caching.")
    default_ttl_seconds: int = Field(default=600, ge=1)


class LLMSettings(BaseModel):
    provider: Literal["openai", "azure", "azure_openai", "anthropic", "custom"] = "openai"
    model: str = "gpt-4o-mini"
    api_key: SecretStr | None = None
    base_url: HttpUrl | None = None
    api_version: str | None = None
    context_window_tokens: int = Field(default=120_000, ge=1000)
    request_timeout_seconds: int = Field(default=60, ge=5, le=600)

    def apply_environment(self) -> None:
        """Populate SDK-required environment vars from settings."""

        if self.provider in {"openai", "custom"}:
            if self.api_key:
                value = self.api_key.get_secret_value()
                os.environ["OPENAI_API_KEY"] = value
            if self.base_url:
                os.environ["OPENAI_BASE_URL"] = str(self.base_url)

        elif self.provider in {"azure", "azure_openai"}:
            if self.api_key:
                value = self.api_key.get_secret_value()
                os.environ["AZURE_OPENAI_API_KEY"] = value
                os.environ["OPENAI_API_KEY"] = value
            if self.base_url:
                os.environ["AZURE_OPENAI_ENDPOINT"] = str(self.base_url)
            if self.api_version:
                os.environ["AZURE_OPENAI_API_VERSION"] = self.api_version
                os.environ["OPENAI_API_VERSION"] = self.api_version


class SubscriptionSettings(BaseModel):
    subscription_duration_days: int = Field(default=30, ge=1)


class RequestLimitSettings(BaseModel):
    max_requests: int = Field(default=5, ge=1)
    interval_seconds: int = Field(default=10, ge=1)
    window_retention_hours: int = Field(default=48, ge=1, le=168)


class SummaryModelSettings(BaseModel):
    provider: Literal["openai", "azure", "azure_openai", "anthropic", "custom"] | None = None
    model: str | None = None
    api_key: SecretStr | None = None
    base_url: HttpUrl | None = None
    api_version: str | None = None

    @field_validator("provider", "model", "api_version", mode="before")
    @classmethod
    def _empty_str_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("base_url", mode="before")
    @classmethod
    def _empty_url_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("api_key", mode="before")
    @classmethod
    def _empty_key_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


class ExternalToolSettings(BaseModel):
    serpapi_api_key: SecretStr | None = None
    serpapi_engine: str = Field(default="google_light", min_length=1)
    jina_reader_base_url: AnyHttpUrl = Field(default="https://r.jina.ai/")
    judge0_api_url: AnyHttpUrl | None = None
    judge0_api_key: SecretStr | None = None
    judge0_language_id: int = Field(default=71, ge=1)
    request_timeout_seconds: int = Field(default=10, ge=1, le=60)


class ZaiSettings(BaseModel):
    base_url: HttpUrl | None = None
    api_key: SecretStr | None = None
    default_model: str | None = None
    summary_model: str | None = None


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BOT_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__"
    )

    environment: Literal["dev", "staging", "prod"] = "dev"
    telegram_token: SecretStr
    telegram_proxy: str | None = None
    webhook_secret: SecretStr | None = None
    default_language: str = "en"
    timezone: str = "UTC"
    admin_telegram_id: int | None = None
    agent_timeout_seconds: int = Field(default=90, ge=5, le=600)

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    summary: SummaryModelSettings | None = None
    external_tools: ExternalToolSettings = Field(default_factory=ExternalToolSettings)
    zai: ZaiSettings | None = None
    subscriptions: SubscriptionSettings = Field(default_factory=SubscriptionSettings)
    request_limit: RequestLimitSettings = Field(default_factory=RequestLimitSettings)

    split_markdown_newlines: bool = True
    enable_markdown_v2: bool = True


@lru_cache
def get_settings() -> BotSettings:
    """Return cached settings instance."""

    return BotSettings()  # type: ignore[call-arg]


__all__ = ["BotSettings", "ExternalToolSettings", "SummaryModelSettings", "get_settings"]
