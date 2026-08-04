"""Every shipped theme must be interchangeable with every other."""

import pytest

from admin_litestar.constants import DEFAULT_THEME, THEMES
from admin_litestar.static import STATIC

# The classes host templates and the package's own templates rely on. A theme
# that leaves one unstyled is a theme a custom page breaks under.
SHARED_CLASSES = (
    ".shell",
    ".side",
    ".brand",
    ".nav-group",
    ".nav-foot",
    ".main",
    ".page",
    ".pad",
    ".bar",
    ".head",
    ".eyebrow",
    ".dot",
    ".title",
    ".actions",
    ".filters",
    ".note",
    ".wrap",
    ".tbl",
    ".chip",
    ".chip--on",
    ".chip--danger",
    ".btn",
    ".btn--primary",
    ".btn--danger",
    ".stats",
    ".stat",
    ".label",
    ".mono",
    ".split",
    ".pane",
    ".record",
    ".tabs",
    ".rows",
    ".row",
    ".form",
    ".form-title",
    ".modal",
    ".modal-head",
    ".clickable",
    ".field",
    ".field-error",
    ".form-error",
    ".toast",
    ".filter-bar",
    ".range",
    ".range-body",
    ".range-field",
    ".segmented",
    ".segment",
    ".segment-count",
    ".charts",
    ".chart",
    ".chart-bar",
    ".spark",
    ".row-actions",
    ".row-select",
    ".bulk",
)


def _stylesheet(theme: str) -> str:
    """Return the text of one theme's stylesheet."""
    return (STATIC / THEMES[theme]).read_text()


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_every_theme_styles_the_shared_classes(theme: str) -> None:
    """A page written against one theme must render under the others."""
    text = _stylesheet(theme)
    missing = [name for name in SHARED_CLASSES if name not in text]
    assert not missing, f"{theme} leaves {missing} unstyled"


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_every_theme_defines_the_six_group_hues(theme: str) -> None:
    """Nav hue coding is part of the contract, not one theme's flourish."""
    text = _stylesheet(theme)
    for index in range(6):
        assert f"--hue-{index}:" in text, f"{theme} does not define --hue-{index}"


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_every_theme_respects_reduced_motion(theme: str) -> None:
    """The quality floor holds whichever theme a host picks."""
    assert "prefers-reduced-motion" in _stylesheet(theme)


@pytest.mark.parametrize("theme", ["classic", "schematic"])
def test_the_following_themes_answer_the_os_preference(theme: str) -> None:
    """These two are drawn twice, once for each ambient preference."""
    text = _stylesheet(theme)
    assert "prefers-color-scheme" in text
    assert '[data-theme="light"]' in text or '[data-theme="dark"]' in text


def test_the_black_theme_commits_to_one_look() -> None:
    """``black`` is deliberately not light-mode aware.

    A strict monochrome scheme inverted for daylight is a different design, not
    the same one lightened -- so this theme declares ``color-scheme: dark`` and
    ignores the ambient preference. Asserted, so it reads as a choice rather
    than as an omission somebody should fix.
    """
    text = _stylesheet("black")
    assert "color-scheme: dark" in text
    assert "prefers-color-scheme" not in text


def test_the_default_theme_is_one_of_the_shipped_ones() -> None:
    """The default cannot name a theme that does not exist."""
    assert DEFAULT_THEME in THEMES
    assert (STATIC / THEMES[DEFAULT_THEME]).is_file()
