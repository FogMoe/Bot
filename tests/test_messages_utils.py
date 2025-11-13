"""Tests for Markdown utility helpers."""

from __future__ import annotations

from app.bot.utils import messages


def test_split_markdown_message_handles_code_blocks():
    text = "First\n```python\nprint('hi')\n```\nSecond"
    parts = messages.split_markdown_message(text)
    assert len(parts) == 3
    assert parts[1].startswith("```python")


def test_iter_fragments_returns_converted_pairs(monkeypatch):
    monkeypatch.setattr(messages, "telegramify_markdown", None)
    result = list(messages.iter_fragments("Line1\n\nLine2"))
    assert result == [("Line1", "Line1"), ("Line2", "Line2")]
