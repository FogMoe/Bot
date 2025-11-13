"""Tests for the I18nService translation lookup and fallback."""

from __future__ import annotations

from pathlib import Path

from app.i18n import I18nService


def test_gettext_returns_translated_string(tmp_path: Path):
    locale_dir = tmp_path / "locales"
    locale_dir.mkdir()
    (locale_dir / "en.json").write_text('{"greet": "Hello {name}"}', encoding="utf-8")
    service = I18nService(locales_path=locale_dir, default_locale="en")

    text = service.gettext("greet", name="World")
    assert text == "Hello World"


def test_gettext_falls_back_to_default(tmp_path: Path):
    locale_dir = tmp_path / "locales"
    locale_dir.mkdir()
    (locale_dir / "en.json").write_text('{"greet": "Hello"}', encoding="utf-8")
    service = I18nService(locales_path=locale_dir, default_locale="en")

    assert service.gettext("greet", locale="es") == "Hello"
    assert service.gettext("missing.key") == "missing.key"
