"""Utility to approximate token counts without external deps."""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    text = text.strip()
    if not text:
        return 0
    return max(1, len(text.split()) * 3 // 2)


__all__ = ["estimate_tokens"]
