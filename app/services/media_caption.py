"""Helpers for converting Telegram media into textual descriptions."""

from __future__ import annotations

from io import BytesIO
from typing import Protocol

from aiogram import Bot
from aiogram.types import Message
from PIL import Image, ImageOps
from pydantic_ai.messages import BinaryImage

from app.agents.media_caption import MediaCaptionAgent
from app.config import BotSettings, get_settings
from app.logging import logger

MAX_SIDE_LENGTH = 1280


class MediaCaptionError(RuntimeError):
    """Raised when media captioning fails and we should fall back to text-only flow."""


class CaptionAgent(Protocol):
    async def describe(self, *, prompt_context: str, image: BinaryImage) -> str: ...


class MediaCaptionService:
    __slots__ = ("settings", "agent")

    def __init__(self, agent: CaptionAgent | None = None, settings: BotSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.agent = agent or MediaCaptionAgent(self.settings)

    async def describe_photo(self, message: Message) -> str:
        if not message.photo:
            raise MediaCaptionError("Photo payload missing")
        photo = message.photo[-1]
        raw, file_path = await self._download_file(message.bot, photo.file_id)
        image_bytes = self._prepare_jpeg(raw, source=file_path or "photo")
        prompt = self._build_prompt(kind="photo")
        image = BinaryImage(data=image_bytes, media_type="image/jpeg")
        return await self.agent.describe(prompt_context=prompt, image=image)

    async def describe_sticker(self, message: Message) -> str:
        sticker = message.sticker
        if sticker is None:
            raise MediaCaptionError("Sticker payload missing")
        if sticker.is_animated:
            raise MediaCaptionError("Animated stickers are not supported yet")
        if sticker.is_video:
            raise MediaCaptionError("Video stickers are not supported yet")
        raw, file_path = await self._download_file(message.bot, sticker.file_id)
        image_bytes = self._prepare_jpeg(raw, source=file_path or "sticker")
        metadata: list[str] = []
        if sticker.emoji:
            metadata.append(f"emoji={sticker.emoji}")
        if sticker.set_name:
            metadata.append(f"set={sticker.set_name}")
        prompt = self._build_prompt(kind="sticker", metadata=metadata)
        image = BinaryImage(data=image_bytes, media_type="image/jpeg")
        return await self.agent.describe(prompt_context=prompt, image=image)

    async def _download_file(self, bot: Bot | None, file_id: str) -> tuple[bytes, str | None]:
        if bot is None:
            raise MediaCaptionError("Bot reference is not available")
        try:
            file = await bot.get_file(file_id)
            buffer = BytesIO()
            await bot.download_file(file.file_path, buffer)
            return buffer.getvalue(), file.file_path
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("media_download_failed", error=str(exc))
            raise MediaCaptionError("Unable to download media from Telegram") from exc

    def _prepare_jpeg(self, raw: bytes, *, source: str) -> bytes:
        try:
            with Image.open(BytesIO(raw)) as image:
                image = ImageOps.exif_transpose(image)
                if max(image.size) > MAX_SIDE_LENGTH:
                    image.thumbnail((MAX_SIDE_LENGTH, MAX_SIDE_LENGTH))
                if image.mode not in ("RGB", "RGBA"):
                    image = image.convert("RGBA") if "A" in image.mode else image.convert("RGB")
                if image.mode == "RGBA":
                    background = Image.new("RGBA", image.size, (255, 255, 255, 255))
                    background.paste(image, mask=image.split()[3])
                    image = background.convert("RGB")
                elif image.mode != "RGB":
                    image = image.convert("RGB")
                buffer = BytesIO()
                image.save(buffer, format="JPEG", quality=90, optimize=True)
            return buffer.getvalue()
        except Exception as exc:  # pragma: no cover - depends on PIL internals
            logger.warning("media_transcode_failed", source=source, error=str(exc))
            raise MediaCaptionError("Failed to normalize media for captioning") from exc

    def _build_prompt(self, *, kind: str, metadata: list[str] | None = None) -> str:
        lines = [
            "Describe the following Telegram media so a text-only assistant can understand it.",
            "Focus on factual visual details, visible text, and overall layout.",
            f"Media kind: {kind}",
        ]
        if metadata:
            lines.append("Details: " + ", ".join(metadata))
        lines.append("Provide the description:")
        return "\n".join(lines)


__all__ = ["MediaCaptionService", "MediaCaptionError"]
