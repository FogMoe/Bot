"""Unit tests for media-specific formatting helpers."""

from __future__ import annotations

from types import SimpleNamespace

from app.bot.routers.chat import _compose_media_user_input_text


def _message(**attrs):
    defaults = {
        "caption": None,
        "reply_to_message": None,
    }
    defaults.update(attrs)
    return SimpleNamespace(**defaults)


def _reply(text: str, *, is_bot: bool = False):
    return SimpleNamespace(
        text=text,
        caption=None,
        from_user=SimpleNamespace(is_bot=is_bot),
    )


def test_compose_media_user_input_without_reply():
    message = _message()
    result = _compose_media_user_input_text(message, kind="photo", description="A sunset over the city")
    assert result == "[PHOTO]\nVision: A sunset over the city"


def test_compose_media_user_input_with_reply_and_caption():
    message = _message(caption="My cat", reply_to_message=_reply("hello"))
    result = _compose_media_user_input_text(message, kind="sticker", description="Cartoon cat waving")
    assert result.startswith('> Quote from User: "hello"')
    assert "Caption: My cat" in result
    assert "Vision: Cartoon cat waving" in result
