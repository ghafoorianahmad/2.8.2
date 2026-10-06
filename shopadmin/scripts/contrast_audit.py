"""WCAG contrast audit for the ShopAdmin theme.

Reads the LIVE values out of ``app.ui.theme`` (the single source of truth) and
computes the contrast ratio of every foreground/background pair the UI actually
renders, plus every literal colour embedded in the stylesheet.

Reports pass/fail for WCAG AA: 4.5:1 for normal text, 3:1 for large text and
non-text UI.

Usage:
    python scripts/contrast_audit.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

#: Literal colours used inside the stylesheet that are not theme constants.
#: (label, foreground, background, minimum ratio)
EXTRA_PAIRS: list[tuple[str, str, str, float]] = [
    ("tooltip: white on INK", "#FFFFFF", "#0F172A", 4.5),
    ("table cell on alternating row", "#1E293B", "#FBFDFF", 4.5),
    ("table cell on selected row", "#1E293B", "#EFF6FF", 4.5),
    ("input error state text", "#1E293B", "#FEF2F2", 4.5),
]

#: Status-pill foreground/background pairs (app/statuses.py).
PILL_PAIRS: list[tuple[str, str, str, float]] = [
    ("در انتظار", "#B45309", "#FEF3C7", 4.5),
    ("تأییدشده", "#047857", "#D1FAE5", 4.5),
    ("ردشده", "#B91C1C", "#FEE2E2", 4.5),
    ("فیش ارسال‌شده", "#1D4ED8", "#DBEAFE", 4.5),
    ("نوشته‌شده", "#0F766E", "#CCFBF1", 4.5),
    ("لغوشده", "#475569", "#E2E8F0", 4.5),
    ("منقضی", "#4B5563", "#F3F4F6", 4.5),
]

#: Non-text UI indicators: WCAG AA requires 3:1 for these.
INDICATOR_PAIRS: list[tuple[str, str, str, float]] = [
    ("checkbox glyph (white check on checked fill)", "#FFFFFF", "#1D4ED8", 3.0),
    ("checkbox border (unchecked) on white", "#475569", "#FFFFFF", 3.0),
    ("radio glyph (white dot on checked fill)", "#FFFFFF", "#1D4ED8", 3.0),
    ("radio border (unchecked) on white", "#475569", "#FFFFFF", 3.0),
    ("disabled checkbox border vs surface", "#5B6B7F", "#FFFFFF", 3.0),
]


def _srgb_to_linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    """WCAG relative luminance of a #RRGGBB colour."""
    text = color.lstrip("#")
    r, g, b = (int(text[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return (
        0.2126 * _srgb_to_linear(r)
        + 0.7152 * _srgb_to_linear(g)
        + 0.0722 * _srgb_to_linear(b)
    )


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG contrast ratio between two #RRGGBB colours."""
    lighter = max(relative_luminance(foreground), relative_luminance(background))
    darker = min(relative_luminance(foreground), relative_luminance(background))
    return (lighter + 0.05) / (darker + 0.05)


def from_theme() -> list[tuple[str, str, str, float]]:
    """Every pair derived from the live theme constants."""
    from app.ui import theme

    return [
        ("TEXT on SURFACE (card body)", theme.TEXT, theme.SURFACE, 4.5),
        ("TEXT on BACKGROUND (window)", theme.TEXT, theme.BACKGROUND, 4.5),
        ("TEXT on HOVER (button hover)", theme.TEXT, theme.HOVER, 4.5),
        ("TEXT_MUTED on SURFACE (hint)", theme.TEXT_MUTED, theme.SURFACE, 4.5),
        ("TEXT_MUTED on BACKGROUND (panel hint)", theme.TEXT_MUTED, theme.BACKGROUND, 4.5),
        ("TEXT_MUTED on header surface", theme.TEXT_MUTED, "#F8FAFC", 4.5),
        ("TEXT_FAINT on SURFACE (auxiliary)", theme.TEXT_FAINT, theme.SURFACE, 4.5),
        ("INK on SURFACE (card value)", theme.INK, theme.SURFACE, 4.5),
        ("white on PRIMARY (primary button)", "#FFFFFF", theme.PRIMARY, 4.5),
        ("white on PRIMARY_DARK (hover)", "#FFFFFF", theme.PRIMARY_DARK, 4.5),
        ("white on PRIMARY_PRESSED", "#FFFFFF", theme.PRIMARY_PRESSED, 4.5),
        ("white on SUCCESS (confirm button)", "#FFFFFF", theme.SUCCESS, 4.5),
        ("white on SUCCESS_DARK (hover)", "#FFFFFF", theme.SUCCESS_DARK, 4.5),
        ("white on DANGER (reject button)", "#FFFFFF", theme.DANGER, 4.5),
        ("white on DANGER_DARK (hover)", "#FFFFFF", theme.DANGER_DARK, 4.5),
        ("white on ROLE_PURPLE", "#FFFFFF", theme.ROLE_PURPLE, 4.5),
        ("DISABLED_TEXT on DISABLED_BG", theme.DISABLED_TEXT, theme.DISABLED_BG, 4.5),
        ("PRIMARY_DARK on HOVER (hover text)", theme.PRIMARY_DARK, theme.HOVER, 4.5),
        ("PRIMARY_DARK on PRIMARY_LIGHT", theme.PRIMARY_DARK, theme.PRIMARY_LIGHT, 4.5),
        ("PRIMARY_DARK on PRIMARY_SOFT (selected nav)", theme.PRIMARY_DARK, theme.PRIMARY_SOFT, 4.5),
        ("PRIMARY_DARK on SELECTED_BG", theme.PRIMARY_DARK, theme.SELECTED_BG, 4.5),
        ("SUCCESS_DARK on SUCCESS_LIGHT", theme.SUCCESS_DARK, theme.SUCCESS_LIGHT, 4.5),
        ("INFO_DARK on INFO_LIGHT", theme.INFO_DARK, theme.INFO_LIGHT, 4.5),
        ("WARNING_TEXT on WARNING_BG (banner)", theme.WARNING_TEXT, theme.WARNING_BG, 4.5),
        ("WARNING_TEXT on SURFACE", theme.WARNING_TEXT, theme.SURFACE, 4.5),
        ("ROLE_PURPLE on SURFACE", theme.ROLE_PURPLE, theme.SURFACE, 4.5),
        ("DANGER on SURFACE (error text)", theme.DANGER, theme.SURFACE, 4.5),
        ("SUCCESS_DARK on SURFACE (ok text)", theme.SUCCESS_DARK, theme.SURFACE, 4.5),
    ]


def stylesheet_literals() -> list[tuple[str, str, str, float]]:
    """Check every QSS rule that sets BOTH a text colour and a background.

    Only the ``color`` and ``background`` *shorthand* properties count: a
    ``border-color`` or ``background-color`` is not text and must not be
    compared as if it were.
    """
    from app.ui import theme

    qss = theme.stylesheet("Vazirmatn")
    found: list[tuple[str, str, str, float]] = []
    for match in re.finditer(r"(?P<sel>[^{}]+)\{(?P<body>[^}]*)\}", qss):
        selector = " ".join(match.group("sel").split())
        body = match.group("body")
        # (?<![-\w]) keeps "background-color" and "border-color" out.
        color = re.search(r"(?<![-\w])color:\s*(#[0-9A-Fa-f]{6})", body)
        background = re.search(r"(?<![-\w])background:\s*(#[0-9A-Fa-f]{6})", body)
        if not color or not background:
            continue
        found.append((f"qss {selector[:52]}", color.group(1), background.group(1), 4.5))
    return found


def main() -> int:
    pairs: list[tuple[str, str, str, float]] = []
    pairs += from_theme()
    pairs += EXTRA_PAIRS
    pairs += PILL_PAIRS
    pairs += INDICATOR_PAIRS
    pairs += stylesheet_literals()

    failures: list[tuple[str, str, str, float, float]] = []
    print(f"{'ratio':>7}  {'min':>4}  result  pair")
    print("-" * 96)
    for label, foreground, background, minimum in pairs:
        ratio = contrast_ratio(foreground, background)
        ok = ratio >= minimum
        if not ok:
            failures.append((label, foreground, background, ratio, minimum))
        print(
            f"{ratio:7.2f}  {minimum:4.1f}  {'  ok  ' if ok else ' FAIL '}  "
            f"{label}  ({foreground} on {background})"
        )

    print("-" * 96)
    print(f"{len(pairs) - len(failures)}/{len(pairs)} pairs meet WCAG AA")
    if failures:
        print(f"\n{len(failures)} FAILING pair(s):")
        for label, foreground, background, ratio, minimum in failures:
            print(f"  {label}: {ratio:.2f} < {minimum} ({foreground} on {background})")
        return 1
    print("All audited pairs meet WCAG AA.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
