"""Tests for the reader color theme controls."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_theme_script_supports_persistence_and_system_preference():
    script = (PROJECT_ROOT / "reader/static/js/theme.js").read_text()

    assert "issued-theme" in script
    assert "prefers-color-scheme: dark" in script
    assert "aria-pressed" in script


def test_dark_theme_styles_are_scoped():
    stylesheet = (PROJECT_ROOT / "reader/static/css/style.css").read_text()

    assert 'html[data-theme="dark"]' in stylesheet
