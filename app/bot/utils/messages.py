"""Formatting helpers for Telegram MarkdownV2."""

from __future__ import annotations

import re
from typing import Iterable

try:
    import telegramify_markdown
except ImportError:  # pragma: no cover
    telegramify_markdown = None  # type: ignore[assignment]

MARKDOWN_V2_SPECIALS = r"_*[]()~`>#+-=|{}.!"
MARKDOWN_ESCAPE_RE = re.compile(f"([{re.escape(MARKDOWN_V2_SPECIALS)}])")


def split_markdown_message(text: str) -> list[str]:
    """Split assistant output by newline unless inside a fenced block."""

    segments: list[str] = []
    buffer: list[str] = []
    in_code = False

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            if not in_code and buffer:
                segments.extend(buffer)
                buffer = []
            in_code = not in_code
            buffer.append(line)
            if not in_code:
                segments.append("\n".join(buffer))
                buffer = []
            continue

        if in_code:
            buffer.append(line)
        else:
            if buffer:
                segments.append("\n".join(buffer))
                buffer = []
            if stripped:
                segments.append(line)

    if buffer:
        segments.append("\n".join(buffer))

    return [segment for segment in segments if segment.strip()]


def to_telegram_markdown(text: str) -> str:
    if telegramify_markdown is None:
        return text
    return telegramify_markdown.markdownify(
        text,
        max_line_length=None,
        normalize_whitespace=False,
    ).strip()


def iter_fragments(text: str) -> Iterable[tuple[str, str]]:
    converted = to_telegram_markdown(text)
    for chunk in split_markdown_message(converted):
        yield chunk, chunk
