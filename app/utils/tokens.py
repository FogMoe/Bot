"""Utility helpers for estimating token counts."""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Approximate tokens using 1 non-ASCII == 1 token, 2 ASCII == 1 token."""

    if not text:
        return 0

    ascii_chars = 0
    non_ascii_chars = 0
    for char in text:
        if char.isascii():
            ascii_chars += 1
        else:
            non_ascii_chars += 1

    tokens_from_ascii = (ascii_chars + 1) // 2
    total = tokens_from_ascii + non_ascii_chars
    return total if total > 0 else 1


__all__ = ["estimate_tokens"]
