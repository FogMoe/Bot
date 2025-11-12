"""Declarative base for SQLAlchemy models."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    """Declarative base with default table naming."""

    @declared_attr.directive
    def __tablename__(cls) -> str:  # noqa: N805
        return cls.__name__.lower()

    id: Mapped[int] = mapped_column(primary_key=True)


__all__ = ["Base"]
