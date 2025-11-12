"""Runtime configuration based on environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseModel):
    dsn: str = Field(
        default="mysql+asyncmy://bot:bot@localhost:3306/telegram_bot",
        description="SQLAlchemy async DSN using asyncmy driver.",
    )
    pool_size: int = Field(default=5, ge=1, le=50)
    max_overflow: int = Field(default=10, ge=0, le=100)
    echo: bool = False


class RedisSettings(BaseModel):
    url: str | None = Field(default=None, description="Redis URL kept for future caching.")
    default_ttl_seconds: int = Field(default=600, ge=1)


class LLMSettings(BaseModel):
    provider: Literal["openai", "azure_openai", "anthropic", "custom"] = "openai"
    model: str = "gpt-4o-mini"
    api_key: SecretStr | None = None
    base_url: HttpUrl | None = None
    context_window_tokens: int = Field(default=120_000, ge=1000)


class SubscriptionSettings(BaseModel):
    free_hourly_limit: int = Field(default=5, ge=1)
    pro_hourly_limit: int = Field(default=50, ge=1)
    subscription_duration_days: int = Field(default=30, ge=1)


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BOT_", env_file=".env", env_file_encoding="utf-8")

    environment: Literal["dev", "staging", "prod"] = "dev"
    telegram_token: SecretStr
    webhook_secret: SecretStr | None = None
    default_language: str = "en"
    timezone: str = "UTC"

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    subscriptions: SubscriptionSettings = Field(default_factory=SubscriptionSettings)

    split_markdown_newlines: bool = True
    enable_markdown_v2: bool = True


@lru_cache
def get_settings() -> BotSettings:
    """Return cached settings instance."""

    return BotSettings()  # type: ignore[call-arg]


__all__ = ["BotSettings", "get_settings"]
