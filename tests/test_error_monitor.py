from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import Chat, ErrorEvent, Message, Update, User

from app.services.error_monitor import ErrorMonitor


class DummyBot:
    def __init__(self) -> None:
        self.sent_messages = []

    async def send_message(self, chat_id, text, parse_mode=None):
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
            }
        )


def _make_update() -> Update:
    chat = Chat(id=999, type="private", title="Diagnostics")
    user = User(id=123, is_bot=False, first_name="Test", last_name="User", username="tester")
    message = Message(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=chat,
        from_user=user,
        text="hello",
    )
    return Update(update_id=77, message=message)


@pytest.mark.asyncio
async def test_error_monitor_skips_without_admin():
    settings = SimpleNamespace(admin_telegram_id=None, environment="test")
    monitor = ErrorMonitor(settings)
    bot = DummyBot()
    event = ErrorEvent(update=_make_update(), exception=RuntimeError("boom"))

    result = await monitor.handle_error(event, bot)

    assert result is UNHANDLED
    assert bot.sent_messages == []


@pytest.mark.asyncio
async def test_error_monitor_sends_notification():
    settings = SimpleNamespace(admin_telegram_id=555, environment="prod")
    monitor = ErrorMonitor(settings)
    bot = DummyBot()
    event = ErrorEvent(update=_make_update(), exception=ValueError("bad input"))

    result = await monitor.handle_error(event, bot)

    assert result is UNHANDLED
    assert len(bot.sent_messages) == 1
    payload = bot.sent_messages[0]
    assert payload["chat_id"] == 555
    assert payload["parse_mode"] is None
    assert "ValueError" in payload["text"]
    assert "bad input" in payload["text"]
    assert "BOT ERROR DETECTED" in payload["text"]
