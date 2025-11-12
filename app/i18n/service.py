"""File-based i18n helper with in-memory caching."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


class I18nService:
    def __init__(self, *, locales_path: str | Path | None = None, default_locale: str = "en") -> None:
        self.locales_path = Path(locales_path or Path(__file__).with_name("locales"))
        self.default_locale = default_locale

    def gettext(self, key: str, *, locale: str | None = None, **kwargs: Any) -> str:
        loc = (locale or self.default_locale).lower()
        text = self._lookup(loc, key)
        if text is None and loc != self.default_locale:
            text = self._lookup(self.default_locale, key)
        if text is None:
            text = key
        return text.format(**kwargs) if kwargs else text

    @lru_cache(maxsize=16)
    def _load_locale(self, locale: str) -> dict[str, str]:
        file_path = self.locales_path / f"{locale}.json"
        if not file_path.exists():
            return {}
        with file_path.open("r", encoding="utf-8") as fp:
            return json.load(fp)

    def _lookup(self, locale: str, key: str) -> str | None:
        table = self._load_locale(locale)
        return table.get(key)


__all__ = ["I18nService"]
