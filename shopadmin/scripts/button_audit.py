"""v2.9.3: button and footer audit of every screen (like ``text_fit_audit.py``).

Walks every page, dialog and wizard step (``audit_screens``) in every look and
checks:

* every push button is as tall as the standard button (one height for all) and
  uses the theme only (no button-local style sheet, a known variant);
* nothing looks like plain text: no text button without a fill and a frame
  («Ghost» is only for a small icon; «LinkButton» is an underlined link);
* buttons in a row never touch or overlap (at least ``MIN_GAP`` apart);
* dialog footers are tidy: the prominent actions (Primary / Success / Danger)
  are together on the right (the start in right-to-left), the other actions
  after them, and «بستن» / «انصراف» last on the left, never prominent;
* v2.9.4: no button looks faint: its frame or its fill stands out from what is
  around it, measured on the screen's pixels (the 2.9.3 «بستن» had a 1.3:1
  frame and looked like plain text). v2.15.0: the owner asked for the live
  site's «مشخصات» (a filled soft button with a soft neutral edge, never a dark
  or coloured frame): at least 1.4:1 - a button without fill and frame is 1:1;
* the theme: every button rule has the same radius, every variant has a
  disabled look (flat, dashed edge, grey text), and a disabled button really
  looks different from an enabled one in every variant (pixels compared).

Exits with 1 and a list when something is wrong.

    python scripts/button_audit.py            (every look)
    python scripts/button_audit.py --quick    (the default look only)
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import audit_screens as screens
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QPushButton,
                               QWidget)

from app.ui import theme, widgets

#: variants with a rule in the theme
VARIANTS = {"", "Primary", "Success", "Danger", "Tab", "RowMenu"}
#: own look on purpose (not a standard push button)
SPECIAL = {"NavButton", "OptionCard", "LinkButton", "Ghost"}
PROMINENT = {"Primary", "Success", "Danger"}
#: the «close / cancel» of a dialog
CLOSE_WORDS = ("بستن", "انصراف", "بعداً", "نه", "خیر")
MIN_GAP = 6
HEIGHT_SLACK = 1
#: average pixel difference (0..255) a disabled button must have from an enabled one
MIN_DISABLED_DIFF = 6.0
#: frame / fill against the surrounding background (v2.9.4: 3:1; v2.15.0: the
#: site's soft «مشخصات» edge, 1.4:1)
MIN_EDGE_CONTRAST = 1.4


def _luminance(color) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(color.red()) + 0.7152 * channel(color.green()) +         0.0722 * channel(color.blue())


def contrast(a, b) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def edge_contrast(image, button: QPushButton, root: QWidget) -> float | None:
    """The best of (frame, fill) against the background just outside the button,
    on both sides at mid-height; the weaker side counts. None = not measurable."""
    effect = button.graphicsEffect()
    if effect is not None and effect.isEnabled():
        return None     # a soft shadow (filled Primary / Success / Danger): drawn apart
    if button.visibleRegion().boundingRect().size() != button.size():
        return None     # partly scrolled out of its view
    ratio = image.devicePixelRatio() or 1.0
    origin = button.mapTo(root, QPoint(0, 0))
    y = int((origin.y() + button.height() // 2) * ratio)
    width, height = image.width(), image.height()
    if not 0 <= y < height:
        return None
    sides = []
    for edge_x, step in ((origin.x(), -1), (origin.x() + button.width() - 1, 1)):
        outside_x = int((edge_x + 3 * step) * ratio)
        if not 0 <= outside_x < width:
            continue
        outside = image.pixelColor(outside_x, y)
        frame = [image.pixelColor(int((edge_x - k * step) * ratio), y) for k in (0, 1)
                 if 0 <= int((edge_x - k * step) * ratio) < width]
        fill_x = int((edge_x - 7 * step) * ratio)
        fill = [image.pixelColor(fill_x, y)] if 0 <= fill_x < width else []
        candidates = [contrast(c, outside) for c in frame + fill]
        if candidates:
            sides.append(max(candidates))
    return min(sides) if sides else None


def _visible_buttons(root: QWidget) -> list[QPushButton]:
    out = []
    for button in root.findChildren(QPushButton):
        if not button.isVisibleTo(root) or button.width() <= 0:
            continue
        parent = button.parentWidget()
        inside_view = False
        while parent is not None and parent is not root:
            if isinstance(parent, (QAbstractItemView, QComboBox)):
                inside_view = True
                break
            parent = parent.parentWidget()
        if inside_view and button.objectName() != "RowMenu":
            continue
        out.append(button)
    return out


def standard_height() -> int:
    sample = QPushButton("نمونه")
    sample.ensurePolished()
    height = sample.sizeHint().height()
    sample.deleteLater()
    return height


def _text(button: QPushButton) -> str:
    return button.text().replace("&", "").strip()


def _is_close(button: QPushButton) -> bool:
    text = _text(button)
    return any(text == word or text.startswith(word + " ") for word in CLOSE_WORDS)


def _footer(root: QWidget, buttons: list[QPushButton]) -> list[QPushButton]:
    """The bottom row of buttons of a dialog (in the bottom quarter)."""
    if not buttons:
        return []
    def center_y(b):
        return b.mapTo(root, QPoint(0, b.height() // 2)).y()
    bottom = max(center_y(b) for b in buttons)
    if bottom < root.height() * 0.75:
        return []
    return [b for b in buttons if abs(center_y(b) - bottom) <= 6 and
            b.objectName() not in SPECIAL]


def problems_in(root: QWidget, where: str, height: int) -> list[str]:
    out: list[str] = []
    buttons = _visible_buttons(root)
    image = root.grab().toImage() if buttons else None
    for button in buttons:
        name = button.objectName()
        label = _text(button) or button.toolTip() or "(بی‌متن)"
        tag = f"{where} › «{label}»"
        if name == "Ghost" and _text(button):
            out.append(f"{tag}: a text button without fill or frame looks like plain text")
            continue
        if name in SPECIAL:
            continue
        if name not in VARIANTS:
            out.append(f"{tag}: unknown button variant «{name}» (no rule in the theme)")
        if button.styleSheet().strip():
            out.append(f"{tag}: button-local style sheet (use the theme variants)")
        if abs(button.height() - height) > HEIGHT_SLACK:
            out.append(f"{tag}: height {button.height()} ≠ standard {height}")
        if image is not None and button.isEnabled():
            measured = edge_contrast(image, button, root)
            if measured is not None and measured < MIN_EDGE_CONTRAST:
                out.append(f"{tag}: looks faint (frame/fill {measured:.2f}:1 against the "
                           f"background, at least {MIN_EDGE_CONTRAST:.1f}:1)")
    # neighbours in one row: never touching
    rows: dict[tuple[int, int], list[QPushButton]] = {}
    for button in buttons:
        if button.objectName() in ("NavButton", "OptionCard"):
            continue
        top = button.mapTo(root, QPoint(0, 0))
        rows.setdefault((id(button.parentWidget()), top.y() // 8), []).append(button)
    for row in rows.values():
        row.sort(key=lambda b: b.mapTo(root, QPoint(0, 0)).x())
        for left, right in zip(row, row[1:]):
            gap = right.mapTo(root, QPoint(0, 0)).x() - (left.mapTo(root, QPoint(0, 0)).x()
                                                         + left.width())
            if gap < MIN_GAP:
                out.append(f"{where} › «{_text(left)}» / «{_text(right)}»: {gap}px apart "
                           f"(at least {MIN_GAP})")
    # dialog footer
    if isinstance(root, QDialog) or "wizard" in where or "server setup" in where:
        footer = _footer(root, buttons)
        x = {id(b): b.mapTo(root, QPoint(0, 0)).x() for b in footer}
        close = [b for b in footer if _is_close(b)]
        prominent = [b for b in footer if b.objectName() in PROMINENT and not _is_close(b)]
        secondary = [b for b in footer if b not in close and b not in prominent]
        for b in close:
            if b.objectName() in PROMINENT and len(footer) > 1:
                out.append(f"{where} › footer «{_text(b)}»: close / cancel must not be prominent")
            others = [o for o in footer if o is not b]
            if others and x[id(b)] > min(x[id(o)] for o in others):
                out.append(f"{where} › footer «{_text(b)}»: close / cancel must be last "
                           "(left-most)")
        if prominent and secondary and \
                min(x[id(b)] for b in prominent) < max(x[id(b)] for b in secondary):
            out.append(f"{where} › footer: prominent actions "
                       f"{[_text(b) for b in prominent]} must be together on the right, before "
                       f"{[_text(b) for b in secondary]}")
    return out


# ---- theme-wide checks ------------------------------------------------------------
_RULE = re.compile(r"(QPushButton[^{]*)\{([^}]*)\}")


def theme_problems(tag: str) -> list[str]:
    out: list[str] = []
    sheet = theme.stylesheet()
    disabled_variants: set[str] = set()
    for selector, body in _RULE.findall(sheet.replace("{{", "{").replace("}}", "}")):
        radius = re.search(r"border-radius:\s*(\d+)px", body)
        special = any(f"#{s}" in selector for s in SPECIAL - {"OptionCard"})
        if radius and not special and int(radius.group(1)) != theme.RADIUS:
            out.append(f"{tag} theme › {selector.strip()}: radius {radius.group(1)} ≠ "
                       f"{theme.RADIUS}")
        if ":disabled" in selector:
            for part in selector.split(","):
                match = re.search(r"QPushButton(?:#(\w+))?:disabled", part)
                if match and "dashed" in body:
                    disabled_variants.add(match.group(1) or "")
    for variant in sorted((VARIANTS | {"Ghost"}) - disabled_variants):
        out.append(f"{tag} theme › QPushButton{'#' + variant if variant else ''}: no dashed "
                   "disabled look")
    # pixels: enabled vs disabled, every variant
    app = screens.app_instance()
    for variant in sorted(VARIANTS):
        button = widgets.button("ارسال", variant={"Primary": "primary", "Success": "success",
                                                  "Danger": "danger"}.get(variant, "default"))
        if variant in ("Tab", "RowMenu"):
            button.setObjectName(variant)
        button.resize(160, standard_height())
        button.show()
        app.processEvents()
        enabled = button.grab().toImage()
        button.setEnabled(False)
        app.processEvents()
        disabled = button.grab().toImage()
        diff = _mean_diff(enabled, disabled)
        if diff < MIN_DISABLED_DIFF:
            out.append(f"{tag} theme › {variant or 'default'}: disabled looks like enabled "
                       f"(difference {diff:.1f} < {MIN_DISABLED_DIFF})")
        button.close()
        button.deleteLater()
    return out


def _mean_diff(a, b) -> float:
    width, height = min(a.width(), b.width()), min(a.height(), b.height())
    total = count = 0
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            pa, pb = a.pixelColor(x, y), b.pixelColor(x, y)
            total += abs(pa.red() - pb.red()) + abs(pa.green() - pb.green()) + \
                abs(pa.blue() - pb.blue())
            count += 3
    return total / count if count else 0.0


def audit_look(app, tmp: Path, look) -> list[str]:
    tag = screens.apply_look(app, look)
    height = standard_height()
    found = theme_problems(tag)
    for where, widget in screens.iter_screens(app, tmp, tag=tag):
        found += problems_in(widget, where, height)
    found += screens.BUILD_PROBLEMS
    screens.BUILD_PROBLEMS.clear()
    return found


def main() -> int:
    app = screens.app_instance()
    looks = screens.looks_from_argv(sys.argv)
    found: list[str] = []
    for look in looks:
        with tempfile.TemporaryDirectory() as tmp:
            problems = audit_look(app, Path(tmp), look)
        print(f"{look[0]:8} {look[1]:6} {look[2]:6}: {len(set(problems))} button problems",
              flush=True)
        found += problems
    unique = sorted({re.sub(r"^\s*\[[^\]]+\] ", "", line) for line in found})
    for line in unique:
        print(line)
    print(f"{len(unique)} button problems in {len(looks)} looks")
    return 1 if unique else 0


if __name__ == "__main__":
    raise SystemExit(main())
