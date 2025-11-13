"""Shared pytest fixtures for database-backed service tests."""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base


class _AsyncSessionWrapper:
    def __init__(self, sync_session) -> None:
        self._sync = sync_session

    async def execute(self, *args, **kwargs):
        return self._sync.execute(*args, **kwargs)

    async def get(self, *args, **kwargs):
        return self._sync.get(*args, **kwargs)

    def add(self, obj) -> None:
        self._sync.add(obj)

    def add_all(self, objs) -> None:
        self._sync.add_all(objs)

    async def flush(self) -> None:
        self._sync.flush()

    async def commit(self) -> None:
        self._sync.commit()

    async def close(self) -> None:
        self._sync.close()


@pytest_asyncio.fixture
async def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    sync_session = SessionLocal()
    try:
        yield _AsyncSessionWrapper(sync_session)
    finally:
        sync_session.close()
        engine.dispose()
