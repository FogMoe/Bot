"""SQLAlchemy models mirroring the MySQL schema."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

timestamp = Annotated[datetime, mapped_column(DateTime, default=datetime.utcnow)]


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    __table_args__ = (UniqueConstraint("code", name="uq_subscription_plans_code"),)

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    hourly_message_limit: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, default=0)
    monthly_price: Mapped[float] = mapped_column()
    is_default: Mapped[bool] = mapped_column(default=False)
    features: Mapped[dict | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    subscriptions: Mapped[list["UserSubscription"]] = relationship(back_populates="plan")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("telegram_id", name="uq_users_telegram_id"),
        UniqueConstraint("username", name="uq_users_username"),
    )

    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(32))
    first_name: Mapped[str | None] = mapped_column(String(64))
    last_name: Mapped[str | None] = mapped_column(String(64))
    language_code: Mapped[str | None] = mapped_column(String(8))
    role: Mapped[str] = mapped_column(
        Enum("user", "admin", "service", name="user_role"), default="user", nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum("active", "blocked", "deleted", "pending", name="user_status"),
        default="active",
        nullable=False,
    )
    timezone: Mapped[str | None] = mapped_column(String(64))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    settings: Mapped["UserSettings"] = relationship(back_populates="user", uselist=False)
    subscriptions: Mapped[list["UserSubscription"]] = relationship(back_populates="user")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user")


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    preferred_model: Mapped[str | None] = mapped_column(String(64))
    markdown_mode: Mapped[str] = mapped_column(
        Enum("auto", "force_markdown", "force_plain", name="markdown_mode"),
        default="auto",
        nullable=False,
    )
    split_newlines: Mapped[bool] = mapped_column(default=True)
    memory_opt_in: Mapped[bool] = mapped_column(default=True)
    notification_opt_in: Mapped[bool] = mapped_column(default=True)
    extra_settings: Mapped[dict | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user: Mapped[User] = relationship(back_populates="settings")


class SubscriptionCard(Base):
    __tablename__ = "subscription_cards"
    __table_args__ = (UniqueConstraint("code", name="uq_subscription_cards_code"),)

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_id: Mapped[int] = mapped_column(ForeignKey("subscription_plans.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("new", "redeemed", "expired", "disabled", name="card_status"),
        default="new",
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    redeemed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON)
    created_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    plan: Mapped[SubscriptionPlan] = relationship()
    redeemed_by_user: Mapped[User | None] = relationship(
        foreign_keys=[redeemed_by_user_id], backref="redeemed_cards"
    )


class UserSubscription(Base):
    __tablename__ = "user_subscriptions"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("subscription_plans.id"))
    source_card_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscription_cards.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        Enum("active", "cancelled", "expired", "pending", name="subscription_status"),
        default="active",
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(default=0)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user: Mapped[User] = relationship(back_populates="subscriptions")
    plan: Mapped[SubscriptionPlan] = relationship(back_populates="subscriptions")
    source_card: Mapped[SubscriptionCard | None] = relationship()


class UsageHourlyQuota(Base):
    __tablename__ = "usage_hourly_quota"
    __table_args__ = (
        UniqueConstraint("user_id", "window_start", name="uq_usage_hourly_quota_user_window"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    window_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)
    last_reset_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user: Mapped[User] = relationship()


class Conversation(Base):
    __tablename__ = "conversations"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str | None] = mapped_column(String(191))
    context_tokens: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        Enum("active", "archived", "closed", name="conversation_status"),
        default="active",
        nullable=False,
    )
    memory_state: Mapped[str] = mapped_column(
        Enum("in_sync", "needs_compress", "compressed", name="memory_state"),
        default="in_sync",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )
    last_interaction_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped[User] = relationship(back_populates="conversations")
    history: Mapped["Message"] = relationship(
        back_populates="conversation",
        uselist=False,
    )
    archive: Mapped["ConversationArchive | None"] = relationship(
        back_populates="conversation",
        uselist=False,
    )


class Message(Base):
    __tablename__ = "messages"

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), unique=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    history: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    message_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    conversation: Mapped[Conversation] = relationship(back_populates="history")
    user: Mapped[User | None] = relationship()


class ConversationArchive(Base):
    __tablename__ = "conversation_archives"

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), unique=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    summary_text: Mapped[str | None] = mapped_column(Text)
    history: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="archive")
    user: Mapped[User] = relationship()


class AgentRun(Base):
    __tablename__ = "agent_runs"

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    trigger_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        Enum("running", "succeeded", "failed", "cancelled", name="agent_status"),
        default="running",
        nullable=False,
    )
    model: Mapped[str | None] = mapped_column(String(64))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    token_usage_prompt: Mapped[int | None] = mapped_column(Integer)
    token_usage_completion: Mapped[int | None] = mapped_column(Integer)
    result_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    conversation: Mapped[Conversation] = relationship()
    trigger_message: Mapped[Message | None] = relationship()


class LongTermMemory(Base):
    __tablename__ = "long_term_memories"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    source_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )
    memory_type: Mapped[str] = mapped_column(
        Enum("fact", "preference", "summary", "other", name="memory_type"), default="fact"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_vector_id: Mapped[str | None] = mapped_column(String(191))
    token_estimate: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped[User] = relationship()
    conversation: Mapped[Conversation | None] = relationship()
    source_message: Mapped[Message | None] = relationship()


class MemoryChunk(Base):
    __tablename__ = "memory_chunks"

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    start_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )
    end_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(
        Enum("raw", "needs_compress", "compressed", name="memory_chunk_state"),
        default="raw",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    conversation: Mapped[Conversation] = relationship()
    start_message: Mapped[Message | None] = relationship(foreign_keys=[start_message_id])
    end_message: Mapped[Message | None] = relationship(foreign_keys=[end_message_id])
    compression: Mapped["MemoryCompression"] = relationship(back_populates="chunk", uselist=False)


class MemoryCompression(Base):
    __tablename__ = "memory_compressions"

    memory_chunk_id: Mapped[int] = mapped_column(
        ForeignKey("memory_chunks.id", ondelete="CASCADE"), unique=True
    )
    compressed_by_model: Mapped[str | None] = mapped_column(String(64))
    compressed_content: Mapped[str | None] = mapped_column(Text)
    compression_ratio: Mapped[float | None] = mapped_column()
    status: Mapped[str] = mapped_column(
        Enum("pending", "succeeded", "failed", name="compression_status"),
        default="pending",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    chunk: Mapped[MemoryChunk] = relationship(back_populates="compression")


class VectorIndexSnapshot(Base):
    __tablename__ = "vector_index_snapshots"

    long_term_memory_id: Mapped[int] = mapped_column(
        ForeignKey("long_term_memories.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    vector_id: Mapped[str | None] = mapped_column(String(191))
    status: Mapped[str] = mapped_column(
        Enum("pending", "synced", "failed", "deleted", name="vector_snapshot_status"),
        default="pending",
        nullable=False,
    )
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    memory: Mapped[LongTermMemory] = relationship()


class RedisCacheHook(Base):
    __tablename__ = "redis_cache_hooks"
    __table_args__ = (UniqueConstraint("cache_key_pattern", name="uq_redis_cache_hooks_pattern"),)

    cache_key_pattern: Mapped[str] = mapped_column(String(191), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String(128))
    ttl_seconds: Mapped[int | None] = mapped_column(Integer)
    schema_version: Mapped[str | None] = mapped_column(String(32))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    user: Mapped[User | None] = relationship()


__all__ = [
    "User",
    "UserSettings",
    "SubscriptionPlan",
    "SubscriptionCard",
    "UserSubscription",
    "UsageHourlyQuota",
    "Conversation",
    "Message",
    "ConversationArchive",
    "AgentRun",
    "LongTermMemory",
    "MemoryChunk",
    "MemoryCompression",
    "VectorIndexSnapshot",
    "RedisCacheHook",
    "AuditLog",
]
