"""Async retry helpers used by agents and services."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")
AsyncFactory = Callable[[], Awaitable[T]]


async def retry_async(
    operation: AsyncFactory[T],
    *,
    max_attempts: int = 3,
    base_delay: float = 0.5,
    logger=None,
    operation_name: str = "operation",
) -> T:
    """Retry an async operation with linear backoff."""

    attempt = 1
    while attempt <= max_attempts:
        try:
            return await operation()
        except Exception as exc:
            if attempt >= max_attempts:
                raise
            delay = base_delay * attempt
            if logger is not None:
                logger.warning(
                    "retrying_operation",
                    operation=operation_name,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    delay=delay,
                    error=str(exc),
                )
            await asyncio.sleep(delay)
            attempt += 1

    # This point is never reached but keeps type-checkers happy.
    raise RuntimeError(f"{operation_name} failed after {max_attempts} attempts")


__all__ = ["retry_async"]
