"""Unit tests for the token estimation helper."""

from app.utils.tokens import estimate_tokens


def test_estimate_tokens_handles_empty():
    assert estimate_tokens("") == 0
    assert estimate_tokens("   \n   ") == 0


def test_estimate_tokens_counts_words():
    assert estimate_tokens("one") == 1
    assert estimate_tokens("one two") == 3  # 2 * 1.5 tokens
    assert estimate_tokens("a b c d") == 6
