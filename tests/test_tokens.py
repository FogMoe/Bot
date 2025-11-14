"""Unit tests for the token estimation helper."""

from app.utils.tokens import estimate_tokens


def test_estimate_tokens_handles_empty():
    assert estimate_tokens("") == 0


def test_estimate_tokens_counts_whitespace():
    assert estimate_tokens("   \n   ") == 4


def test_estimate_tokens_counts_ascii_pairs():
    assert estimate_tokens("ab") == 1
    assert estimate_tokens("abc") == 2
    assert estimate_tokens("a b c d") == 4


def test_estimate_tokens_counts_non_ascii_per_char():
    assert estimate_tokens("你好") == 2
    assert estimate_tokens("你 好") == 3


def test_estimate_tokens_handles_mixed_text():
    assert estimate_tokens("hi你好") == 3
    assert estimate_tokens("OK，好的") == 4
