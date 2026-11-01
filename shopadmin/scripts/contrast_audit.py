"""WCAG contrast audit for the ShopAdmin theme.

Reads the LIVE values out of ``app.ui.theme`` (the single source of truth) and
computes the contrast ratio of every foreground/background pair the UI actually
renders, plus every literal colour embedded in the stylesheet.

Reports pass/fail for WCAG AA: 4.5:1 for normal text, 3:1 for large text and
non-text UI.

Usage:
    python scripts/contrast_audit.py          (the default look, plus rendered windows)
    python scripts/contrast_audit.py --all    (v2.9.0: also every palette × light / dark)
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
        ("TEXT_MUTED on HEADER_BG (table header)", theme.TEXT_MUTED, theme.HEADER_BG, 4.5),
        ("TEXT_FAINT on SURFACE (auxiliary)", theme.TEXT_FAINT, theme.SURFACE, 4.5),
        ("INK on SURFACE (card value)", theme.INK, theme.SURFACE, 4.5),
        ("white on PRIMARY (primary button)", "#FFFFFF", theme.PRIMARY, 4.5),
        # v2.15.0: the site's «ثبت سفارش» gradient (bold text; the site itself has 1.7:1)
        *[(f"white bold on the primary gradient stop {c}", "#FFFFFF", c, 3.0)
          for c in theme.SITE_GRAD],
        ("white on PRIMARY_DARK (hover)", "#FFFFFF", theme.PRIMARY_DARK, 4.5),
        ("white on PRIMARY_PRESSED", "#FFFFFF", theme.PRIMARY_PRESSED, 4.5),
        ("white on SUCCESS_FILL (confirm button)", "#FFFFFF", theme.SUCCESS_FILL, 4.5),
        ("white on SUCCESS_FILL_DARK (hover)", "#FFFFFF", theme.SUCCESS_FILL_DARK, 4.5),
        ("white on DANGER_FILL (reject button)", "#FFFFFF", theme.DANGER_FILL, 4.5),
        ("white on DANGER_FILL_DARK (hover)", "#FFFFFF", theme.DANGER_FILL_DARK, 4.5),
        # a fill with white text only in the light look (dark: it is a text colour)
        *([("white on ROLE_PURPLE", "#FFFFFF", theme.ROLE_PURPLE, 4.5)]
          if theme.MODE == "light" else []),
        ("DISABLED_TEXT on DISABLED_BG", theme.DISABLED_TEXT, theme.DISABLED_BG, 4.5),
        ("PRIMARY_TEXT on HOVER (hover text)", theme.PRIMARY_TEXT, theme.HOVER, 4.5),
        ("PRIMARY_TEXT on PRIMARY_LIGHT", theme.PRIMARY_TEXT, theme.PRIMARY_LIGHT, 4.5),
        ("PRIMARY_TEXT on PRIMARY_SOFT (selected tab / option)", theme.PRIMARY_TEXT,
         theme.PRIMARY_SOFT, 4.5),
        ("PRIMARY_TEXT on SELECTED_BG", theme.PRIMARY_TEXT, theme.SELECTED_BG, 4.5),
        ("PRIMARY_TEXT on SURFACE (links)", theme.PRIMARY_TEXT, theme.SURFACE, 4.5),
        ("TEXT on GLOW (window corner, full effects)", theme.TEXT, theme.GLOW, 4.5),
        ("SIDEBAR_TEXT on SIDEBAR_BG2 (bar bottom)", theme.SIDEBAR_TEXT, theme.SIDEBAR_BG2, 4.5),
        ("white on SIDEBAR_ACTIVE2 (nav checked end)", "#FFFFFF", theme.SIDEBAR_ACTIVE2, 4.5),
        ("SUCCESS_DARK on SUCCESS_LIGHT", theme.SUCCESS_DARK, theme.SUCCESS_LIGHT, 4.5),
        ("INFO_DARK on INFO_LIGHT", theme.INFO_DARK, theme.INFO_LIGHT, 4.5),
        ("WARNING_TEXT on WARNING_BG (banner)", theme.WARNING_TEXT, theme.WARNING_BG, 4.5),
        ("WARNING_TEXT on SURFACE", theme.WARNING_TEXT, theme.SURFACE, 4.5),
        ("ROLE_PURPLE on SURFACE", theme.ROLE_PURPLE, theme.SURFACE, 4.5),
        ("DANGER on SURFACE (error text)", theme.DANGER, theme.SURFACE, 4.5),
        ("SUCCESS_DARK on SURFACE (ok text)", theme.SUCCESS_DARK, theme.SURFACE, 4.5),
        ("SIDEBAR_TEXT on SIDEBAR_BG (nav)", theme.SIDEBAR_TEXT, theme.SIDEBAR_BG, 4.5),
        ("SIDEBAR_MUTED on SIDEBAR_BG", theme.SIDEBAR_MUTED, theme.SIDEBAR_BG, 4.5),
        ("SIDEBAR_TEXT on SIDEBAR_HOVER", theme.SIDEBAR_TEXT, theme.SIDEBAR_HOVER, 4.5),
        ("white on SIDEBAR_HOVER (nav hover)", "#FFFFFF", theme.SIDEBAR_HOVER, 4.5),
        ("white on SIDEBAR_ACTIVE (nav checked)", "#FFFFFF", theme.SIDEBAR_ACTIVE, 4.5),
        ("SIDEBAR_OK on SIDEBAR_BG", theme.SIDEBAR_OK, theme.SIDEBAR_BG, 4.5),
        ("SIDEBAR_BAD on SIDEBAR_BG", theme.SIDEBAR_BAD, theme.SIDEBAR_BG, 4.5),
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


#: Dialog buttons as the stylesheet defines them (default = plain QPushButton,
#: e.g. the OK button of a QMessageBox; primary = MessageDialog «باشه»).
DIALOG_BUTTON_PAIRS: list[tuple[str, str, str, float]] = [
    ("dialog default button (QMessageBox OK): TEXT on SURFACE", "#1E293B", "#FFFFFF", 4.5),
    ("dialog primary button: white on PRIMARY", "#FFFFFF", "#2563EB", 4.5),
    ("dialog danger button: white on DANGER", "#FFFFFF", "#DC2626", 4.5),
]


# --------------------------------------------------------------------------
# rendered check: what Qt REALLY paints
#
# The static pairs above cannot see cascade bugs, e.g. a window stylesheet
# with an unscoped "background:" that repaints a primary button light while
# its text stays white (the invisible «ادامه» bug). These checks render the
# real windows and dialogs offscreen and measure the button pixels.
# --------------------------------------------------------------------------
def measure_widget(widget) -> tuple[str, str, float]:
    """(background, text colour, ratio) of a rendered button.

    Background = most frequent colour inside the border; text = the frequent
    colour with the highest contrast against it (anti-aliasing produces only
    a few pixels of each intermediate shade, so they are ignored).
    """
    from collections import Counter

    image = widget.grab().toImage()
    w, h = image.width(), image.height()
    counts: Counter = Counter()
    for y in range(3, max(4, h - 3)):
        for x in range(3, max(4, w - 3)):
            counts[image.pixelColor(x, y).name()] += 1
    background = counts.most_common(1)[0][0]
    total = sum(counts.values())
    # A wide button with a short word has very few text pixels, so the floor
    # is small; single anti-aliasing shades still stay below it.
    candidates = [c for c, n in counts.items() if n >= max(6, total * 0.001) and c != background]
    if not candidates:
        return background, background, 1.0
    text = max(candidates, key=lambda c: contrast_ratio(c, background))
    return background, text, contrast_ratio(text, background)


def rendered_pairs() -> list[tuple[str, str, str, float]]:
    """Render wizards, login and dialogs; return measured (label, fg, bg, min)."""
    import os
    import tempfile

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

    from app.api_client import ShopApiClient
    from app.auth import AuthService
    from app.store import Store
    from app.ui import theme, widgets
    from app.ui.login_window import LoginWindow
    from app.ui.wizard import SetupWizard

    app = QApplication.instance() or QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    theme.apply_theme(app)

    def settle() -> None:
        for _ in range(10):
            app.processEvents()

    results: list[tuple[str, str, str, float]] = []

    def check(label: str, button) -> None:
        settle()
        background, text, _ratio = measure_widget(button)
        results.append((f"rendered {label}", text, background, 4.5))

    tmp = tempfile.mkdtemp(prefix="contrast-audit-")
    stores: list = []
    windows: list = []
    try:
        store = Store(os.path.join(tmp, "w.db"))
        stores.append(store)
        wizard = SetupWizard(store, AuthService(store, ShopApiClient()))
        wizard.show()
        windows.append(wizard)
        check("setup wizard «ادامه»", wizard.next_button)

        login_store = Store(os.path.join(tmp, "l.db"))
        stores.append(login_store)
        login_store.configure_connection("http://shopapi.test")
        login = LoginWindow(login_store, AuthService(login_store, ShopApiClient()))
        login.show()
        windows.append(login)
        primaries = [b for b in login.findChildren(QPushButton) if b.objectName() == "Primary"]
        for index, button in enumerate(primaries):
            check(f"login primary #{index + 1} «{button.text().strip()}»", button)

        try:
            from app.ui.server_setup_wizard import ServerSetupWizard

            server_wizard = ServerSetupWizard()
            server_wizard.show()
            windows.append(server_wizard)
            check("server setup wizard «ادامه»", server_wizard.next_button)
        except ImportError:
            server_wizard = None  # client build without the server setup

        parents = [("no parent", None), ("over setup wizard", wizard), ("over login", login)]
        if server_wizard is not None:
            parents.append(("over server wizard", server_wizard))
        for where, parent in parents:
            dialog = widgets.MessageDialog(parent, "خطا", "نمونهٔ پیام خطا", "error")
            dialog.show()
            check(f"error dialog «باشه» ({where})", dialog.ok_button)
            dialog.close()

            confirm = widgets.ConfirmDialog(parent, "تأیید", "نمونه", kind="warning")
            confirm.show()
            for button in confirm.findChildren(QPushButton):
                check(f"confirm dialog «{button.text().strip()}» ({where})", button)
            confirm.close()

            box = QMessageBox(QMessageBox.Icon.Critical, "خطا", "نمونهٔ پیام", QMessageBox.StandardButton.Ok, parent)
            box.show()
            check(f"QMessageBox OK ({where})", box.button(QMessageBox.StandardButton.Ok))
            box.close()
    finally:
        from PySide6.QtCore import QThreadPool

        QThreadPool.globalInstance().waitForDone(10_000)
        settle()
        for window in windows:
            window.close()
        for store in stores:
            try:
                store.close()
            except Exception:  # noqa: BLE001
                pass
    return results


def all_looks() -> list[tuple[str, str, str, float]]:
    """v2.9.0: the theme pairs and stylesheet literals in every palette × mode."""
    from app.ui import theme

    before = (theme.PALETTE, theme.MODE)
    out: list[tuple[str, str, str, float]] = []
    try:
        for palette in theme.PALETTE_NAMES:
            for mode in ("light", "dark"):
                theme.set_mode(mode, palette)
                out += [(f"[{palette}/{mode}] {label}", fg, bg, minimum)
                        for label, fg, bg, minimum in from_theme() + stylesheet_literals()]
    finally:
        theme.set_mode(before[1], before[0])
    return out


def main() -> int:
    pairs: list[tuple[str, str, str, float]] = []
    if "--all" in sys.argv:
        pairs += all_looks()
    pairs += from_theme()
    pairs += EXTRA_PAIRS
    pairs += PILL_PAIRS
    pairs += INDICATOR_PAIRS
    pairs += DIALOG_BUTTON_PAIRS
    pairs += stylesheet_literals()
    if "--no-render" not in sys.argv:
        pairs += rendered_pairs()

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
