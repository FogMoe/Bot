"""Pydantic models shared across logic/application layers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class UserModel(BaseModel):
    id: int
    telegram_id: int
    username: str | None = None
    language_code: str | None = None
    role: Literal["user", "admin", "service"] = "user"
    status: Literal["active", "blocked", "deleted", "pending"] = "active"


class UsageQuotaModel(BaseModel):
    hourly_limit: int
    used_messages: int
    window_start: datetime


class SubscriptionPlanModel(BaseModel):
    id: int
    code: str
    name: str
    hourly_message_limit: int


__all__ = [
    "UserModel",
    "UsageQuotaModel",
    "SubscriptionPlanModel",
]
