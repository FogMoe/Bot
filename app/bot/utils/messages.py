"""Formatting helpers for Telegram MarkdownV2."""

from __future__ import annotations

import re
from typing import Iterable

MARKDOWN_V2_SPECIALS = r"_*[]()~`>#+-=|{}.!"
MARKDOWN_ESCAPE_RE = re.compile(f"([{re.escape(MARKDOWN_V2_SPECIALS)}])")


def escape_markdown(text: str) -> str:
    return MARKDOWN_ESCAPE_RE.sub(r"\\\1", text)


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


def iter_fragments(text: str) -> Iterable[tuple[str, str]]:
    for chunk in split_markdown_message(text):
        if chunk.startswith("```"):
            yield chunk, chunk
        else:
            yield chunk, escape_markdown(chunk)
