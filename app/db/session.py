"""Async SQLAlchemy session management."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import BotSettings, get_settings
from app.logging import logger


class Database:
    """Lazy SQLAlchemy engine/session factory wrapper."""

    def __init__(self, settings: BotSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self._engine = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    def _ensure_engine(self) -> None:
        if self._engine is None:
            db_cfg = self.settings.database
            self._engine = create_async_engine(
                db_cfg.dsn,
                echo=db_cfg.echo,
                pool_size=db_cfg.pool_size,
                max_overflow=db_cfg.max_overflow,
                pool_recycle=db_cfg.pool_recycle,
                pool_pre_ping=db_cfg.pool_pre_ping,
            )
            self._session_factory = async_sessionmaker(
                bind=self._engine,
                expire_on_commit=False,
                autoflush=False,
            )
            logger.info("db_engine_initialized", dsn=db_cfg.dsn)

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        self._ensure_engine()
        assert self._session_factory is not None
        return self._session_factory

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        factory = self.session_factory
        async with factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise


def get_database(settings: BotSettings | None = None) -> Database:
    return Database(settings=settings)


SessionProvider = Callable[[], Database]

__all__ = ["Database", "get_database", "SessionProvider"]
