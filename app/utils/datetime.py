"""Time utilities with timezone-aware defaults."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return current UTC time with tzinfo."""

    return datetime.now(timezone.utc)


__all__ = ["utc_now"]
