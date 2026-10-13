"""Design tokens: soft modern palette, spacing, radii and the global RTL theme.

One calm blue accent on a white background, generous sizes for readable Persian
text, and rounded controls with clear hover states.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QWidget

from ..paths import fonts_dir

# --------------------------------------------------------------------------
# palette
#
# Every foreground/background pair below is verified against WCAG AA by
# scripts/contrast_audit.py (4.5:1 for normal text, 3:1 for large text and
# non-text UI). Do not darken/lighten a colour here without re-running it.
# --------------------------------------------------------------------------
PRIMARY = "#2563EB"          # white text on this = 5.17:1
PRIMARY_DARK = "#1D4ED8"     # white text on this = 6.70:1
PRIMARY_PRESSED = "#1E40AF"  # white text on this = 8.72:1
PRIMARY_LIGHT = "#DBEAFE"
PRIMARY_SOFT = "#EFF6FF"

# Solid button fills carry WHITE text, so they must be dark enough. The light
# tints are only used as backgrounds for DARK text, never behind white text.
SUCCESS = "#047857"          # white text on this = 5.48:1
SUCCESS_DARK = "#065F46"     # white text on this = 7.68:1
SUCCESS_LIGHT = "#D1FAE5"

WARNING = "#D97706"
WARNING_TEXT = "#92400E"     # on WARNING_BG = 6.84:1
WARNING_LIGHT = "#FEF3C7"
WARNING_BG = "#FFFBEB"
WARNING_BORDER = "#FCD34D"

DANGER = "#DC2626"           # white text on this = 4.83:1
DANGER_DARK = "#B91C1C"      # white text on this = 6.47:1
DANGER_LIGHT = "#FEE2E2"

INFO = "#0891B2"
INFO_DARK = "#155E75"        # on INFO_LIGHT = 5.49:1
INFO_LIGHT = "#CFFAFE"

ROLE_PURPLE = "#7C3AED"      # white text on this = 5.70:1

INK = "#0F172A"
TEXT = "#1E293B"
TEXT_MUTED = "#475569"       # on white = 7.48:1 (was #64748B, only 4.76:1)
TEXT_FAINT = "#5B6B7F"       # on white = 5.30:1 (was #94A3B8, only 2.56:1)
BORDER = "#E2E8F0"
BORDER_STRONG = "#CBD5E1"
SURFACE = "#FFFFFF"
BACKGROUND = "#F6F8FB"
SIDEBAR_BG = "#0F172A"
SIDEBAR_TEXT = "#CBD5E1"        # on SIDEBAR_BG = 12.0:1
SIDEBAR_MUTED = "#94A3B8"       # on SIDEBAR_BG = 6.96:1
SIDEBAR_HOVER = "#1E293B"       # SIDEBAR_TEXT on it = 9.8:1
SIDEBAR_ACTIVE = "#1D4ED8"      # white on it = 6.70:1
SIDEBAR_OK = "#6EE7B7"          # on SIDEBAR_BG = 11.5:1
SIDEBAR_BAD = "#FCA5A5"         # on SIDEBAR_BG = 8.9:1
HOVER = "#F1F5F9"
SELECTED_BG = "#EFF6FF"

# Disabled controls keep AAA-grade legibility instead of fading into the panel.
DISABLED_BG = "#F1F5F9"
DISABLED_TEXT = "#5B6B7F"

# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------
RADIUS_SM = 8
RADIUS = 12
RADIUS_LG = 16
SPACE_XS = 4
SPACE_SM = 8
SPACE = 16
SPACE_LG = 24
SPACE_XL = 32

FONT_FAMILY_FALLBACKS = ("Vazirmatn", "Vazir", "Sahel", "IRANSans", "Tahoma", "Segoe UI", "Arial")
BASE_FONT_SIZE = 10

_resolved_family: str | None = None


# --------------------------------------------------------------------------
# fonts
# --------------------------------------------------------------------------
#: Windows fonts registered as a fallback when no font is bundled/registered.
#: The Qt "offscreen" platform (used by CI and the screenshot tool) starts with
#: an EMPTY font database, so without this the UI would render tofu boxes.
SYSTEM_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\tahoma.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
)


def load_application_fonts() -> list[str]:
    """Register every bundled Persian font. Returns the loaded family names."""
    loaded: list[str] = []
    directory = fonts_dir()
    if directory.exists():
        for path in sorted(directory.glob("*.ttf")) + sorted(directory.glob("*.otf")):
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id != -1:
                loaded.extend(QFontDatabase.applicationFontFamilies(font_id))
    if not QFontDatabase.families():
        # Nothing registered yet: fall back to the operating system's fonts.
        import os

        for candidate in SYSTEM_FONT_CANDIDATES:
            if not os.path.exists(candidate):
                continue
            font_id = QFontDatabase.addApplicationFont(candidate)
            if font_id != -1:
                loaded.extend(QFontDatabase.applicationFontFamilies(font_id))
    return loaded


def resolve_font_family(loaded: list[str] | None = None) -> str:
    """Pick the best available Persian font family."""
    global _resolved_family
    if _resolved_family:
        return _resolved_family
    available = set(QFontDatabase.families())
    for family in (loaded or []) + list(FONT_FAMILY_FALLBACKS):
        if family in available:
            _resolved_family = family
            return family
    _resolved_family = "Tahoma"
    return _resolved_family


def app_font(size: int = BASE_FONT_SIZE, bold: bool = False) -> QFont:
    font = QFont(resolve_font_family(), size)
    font.setBold(bold)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


# --------------------------------------------------------------------------
# icons (SVG rendered to a pixmap, coloured on demand)
# --------------------------------------------------------------------------
_ICON_CACHE: dict[tuple[str, int, str], QIcon] = {}

ICONS: dict[str, str] = {
    "dashboard": '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
    "customers": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "orders": '<path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/>',
    "products": '<path d="m7.5 4.27 9 5.15"/><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
    "reports": '<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M7 15l3-4 4 3 5-7"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1.08-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6h.09A1.65 1.65 0 0 0 10.6 3V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9v.09a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M19 8v6"/><path d="M22 11h-6"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "close": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "warning": '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "error": '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
    "success": '<circle cx="12" cy="12" r="10"/><path d="m8 12 3 3 5-6"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
    "inbox": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11Z"/>',
    "file": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v6h6"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/>',
    "eye": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
    "eye_off": '<path d="M9.9 4.24A9.1 9.1 0 0 1 12 4c6.4 0 10 7 10 7a17 17 0 0 1-2.2 3.2"/><path d="M6.6 6.6A17 17 0 0 0 2 11s3.6 7 10 7a9 9 0 0 0 4.5-1.2"/><path d="m2 2 20 20"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "edit": '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4Z"/>',
    "trash": '<path d="M3 6h18"/><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>',
    "key": '<circle cx="7.5" cy="15.5" r="4.5"/><path d="m10.5 12.5 8-8"/><path d="m16 7 3 3"/><path d="m19 4 3 3"/>',
    "chart": '<path d="M3 3v18h18"/><rect x="7" y="12" width="3" height="6"/><rect x="12" y="8" width="3" height="10"/><rect x="17" y="5" width="3" height="13"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
    "wifi": '<path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><path d="M12 20h.01"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/>',
    "box": '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/>',
    "receipt": '<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/><path d="M8 7h8"/><path d="M8 11h8"/><path d="M8 15h5"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>',
    "folder": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "filter": '<path d="M22 3H2l8 9.46V19l4 2v-8.54Z"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/>',
    "server": '<rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><path d="M6 6h.01"/><path d="M6 18h.01"/>',
}


def icon_svg(name: str, color: str = TEXT, width: float = 2.0) -> str:
    body = ICONS.get(name, ICONS["info"])
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{width}" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    )


def icon_pixmap(name: str, size: int = 20, color: str = TEXT) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(icon_svg(name, color).encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


def icon(name: str, size: int = 20, color: str = TEXT) -> QIcon:
    key = (name, size, color)
    if key not in _ICON_CACHE:
        _ICON_CACHE[key] = QIcon(icon_pixmap(name, size, color))
    return _ICON_CACHE[key]


def nav_icon(name: str, size: int = 20) -> QIcon:
    """Sidebar icon: light on the dark bar, white when the button is checked."""
    key = (f"nav:{name}", size, "")
    if key not in _ICON_CACHE:
        result = QIcon()
        normal = icon_pixmap(name, size, SIDEBAR_TEXT)
        active = icon_pixmap(name, size, "#FFFFFF")
        result.addPixmap(normal, QIcon.Mode.Normal, QIcon.State.Off)
        result.addPixmap(active, QIcon.Mode.Normal, QIcon.State.On)
        result.addPixmap(active, QIcon.Mode.Active, QIcon.State.Off)
        result.addPixmap(active, QIcon.Mode.Active, QIcon.State.On)
        _ICON_CACHE[key] = result
    return _ICON_CACHE[key]


def dot_pixmap(color: str, diameter: int = 12) -> QPixmap:
    pixmap = QPixmap(diameter, diameter)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, diameter - 1, diameter - 1)
    painter.end()
    return pixmap


# --------------------------------------------------------------------------
# checkbox / radio indicator glyphs
#
# A checked QCheckBox/QRadioButton would be a plain blue square with no mark —
# the user could not tell whether "مرا به خاطر بسپار" was ticked. Qt style
# sheets cannot draw a checkmark themselves and, unlike a browser, do NOT load
# ``data:`` URIs in ``image: url(...)`` (the glyph silently never appeared).
# So the two glyphs are rendered to small PNG files once and the stylesheet
# points at those real files.
# --------------------------------------------------------------------------
INDICATOR_SIZE = 18
_CHECK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="#FFFFFF" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M19.5 6.5 9.5 16.5l-5-5"/></svg>'
)
_RADIO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<circle cx="12" cy="12" r="5.5" fill="#FFFFFF"/></svg>'
)


def _render_glyph(svg: str, target: Path) -> bool:
    from PySide6.QtGui import QImage

    image = QImage(INDICATOR_SIZE, INDICATOR_SIZE, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        return False
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, INDICATOR_SIZE, INDICATOR_SIZE))
    painter.end()
    return image.save(str(target), "PNG")


def indicator_images() -> tuple[str, str]:
    """(check, radio-dot) PNG paths for the stylesheet; ``""`` when unavailable."""
    import tempfile

    folder = Path(tempfile.gettempdir()) / "ShopAdmin-ui"
    result = []
    for name, svg in (("check.png", _CHECK_SVG), ("radio.png", _RADIO_SVG)):
        target = folder / name
        try:
            folder.mkdir(parents=True, exist_ok=True)
            ok = _render_glyph(svg, target)
        except OSError:
            ok = False
        result.append(target.as_posix() if ok else "")
    return result[0], result[1]


# --------------------------------------------------------------------------
# global stylesheet + RTL
# --------------------------------------------------------------------------
# NOTE: the font family is resolved lazily in :func:`apply_theme`. Calling
# QFontDatabase before a QGuiApplication exists aborts the process, so the
# stylesheet template must never touch Qt at import time.
_STYLESHEET_TEMPLATE = f"""
QWidget {{
    font-family: "__FONT_FAMILY__";
    font-size: {BASE_FONT_SIZE}pt;
    color: {TEXT};
}}
QMainWindow, QDialog {{ background: {BACKGROUND}; }}

QToolTip {{
    background: {INK}; color: #FFFFFF; border: none; padding: 6px 10px;
    border-radius: {RADIUS_SM}px; font-size: {BASE_FONT_SIZE}pt;
}}

/* ---------------- cards / panels ---------------- */
QFrame#Card {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS_LG}px;
}}
QFrame#Panel {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS}px;
}}
QLabel#CardTitle {{ color: {TEXT_MUTED}; font-size: {BASE_FONT_SIZE}pt; }}
QLabel#CardValue {{ color: {INK}; font-size: 21pt; font-weight: 700; }}
QLabel#PageTitle {{ color: {INK}; font-size: 15pt; font-weight: 700; }}
QLabel#PageSubtitle {{ color: {TEXT_MUTED}; font-size: {BASE_FONT_SIZE}pt; }}
QLabel#SectionTitle {{ color: {INK}; font-size: 11pt; font-weight: 600; }}
QLabel#Muted {{ color: {TEXT_MUTED}; }}
QLabel#Faint {{ color: {TEXT_FAINT}; }}
QLabel#EmptyTitle {{ color: {TEXT}; font-size: 12pt; font-weight: 600; }}
QLabel#EmptyHint {{ color: {TEXT_MUTED}; }}

/* ---------------- buttons ---------------- */
QPushButton {{
    background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER_STRONG};
    border-radius: {RADIUS_SM}px; padding: 7px 14px; font-size: {BASE_FONT_SIZE}pt;
    min-height: 20px;
}}
QPushButton:hover {{ background: {HOVER}; border-color: {PRIMARY}; color: {PRIMARY_DARK}; }}
QPushButton:pressed {{ background: {PRIMARY_LIGHT}; }}
QPushButton:disabled {{
    background: {DISABLED_BG}; color: {DISABLED_TEXT}; border-color: {BORDER};
}}

QPushButton#Primary {{
    background: {PRIMARY}; color: #FFFFFF; border: 1px solid {PRIMARY};
    font-weight: 600; padding: 8px 18px;
}}
QPushButton#Primary:hover {{ background: {PRIMARY_DARK}; border-color: {PRIMARY_DARK}; color: #FFFFFF; }}
QPushButton#Primary:pressed {{ background: {PRIMARY_PRESSED}; }}
QPushButton#Primary:disabled {{
    background: {DISABLED_BG}; border-color: {BORDER}; color: {DISABLED_TEXT};
}}

QPushButton#Success {{ background: {SUCCESS}; color: #FFFFFF; border: 1px solid {SUCCESS}; font-weight: 600; }}
QPushButton#Success:hover {{ background: {SUCCESS_DARK}; border-color: {SUCCESS_DARK}; color: #FFFFFF; }}
QPushButton#Success:disabled {{
    background: {DISABLED_BG}; border-color: {BORDER}; color: {DISABLED_TEXT};
}}

QPushButton#Danger {{ background: {DANGER}; color: #FFFFFF; border: 1px solid {DANGER}; font-weight: 600; }}
QPushButton#Danger:hover {{ background: {DANGER_DARK}; border-color: {DANGER_DARK}; color: #FFFFFF; }}
QPushButton#Danger:disabled {{
    background: {DISABLED_BG}; border-color: {BORDER}; color: {DISABLED_TEXT};
}}

QPushButton#Ghost {{ background: transparent; border: none; color: {TEXT_MUTED}; padding: 6px 10px; }}
QPushButton#Ghost:hover {{ background: {HOVER}; color: {PRIMARY_DARK}; }}

QPushButton#NavButton {{
    background: transparent; border: none; border-radius: {RADIUS}px;
    padding: 10px 12px; text-align: right; font-size: 11pt; color: {SIDEBAR_TEXT};
}}
QPushButton#NavButton:hover {{ background: {SIDEBAR_HOVER}; color: #FFFFFF; }}
QPushButton#NavButton:checked {{
    background: {SIDEBAR_ACTIVE}; color: #FFFFFF; font-weight: 700;
}}
QPushButton#NavButton[hasBadge="true"] {{ color: #FDE68A; font-weight: 700; }}
QPushButton#NavButton[hasBadge="true"]:checked {{ color: #FFFFFF; }}
QFrame#Sidebar QLabel {{ background: transparent; }}
QLabel#SidebarTitle {{ color: #FFFFFF; font-size: 12pt; font-weight: 700; }}
QLabel#SidebarMuted {{ color: {SIDEBAR_MUTED}; }}

QPushButton#Tab {{
    border: none; border-radius: {RADIUS_SM}px; padding: 7px 16px;
    background: transparent; color: {TEXT_MUTED}; font-size: {BASE_FONT_SIZE}pt;
}}
QPushButton#Tab:hover {{ background: {HOVER}; color: {TEXT}; }}
QPushButton#Tab:checked {{ background: {PRIMARY}; color: #FFFFFF; font-weight: 600; }}

QPushButton#LinkButton {{
    border: none; background: transparent; color: {PRIMARY}; padding: 2px 4px;
    text-decoration: underline; text-align: right;
}}
QPushButton#LinkButton:hover {{ color: {PRIMARY_DARK}; }}

/* ---------------- inputs ---------------- */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox, QDateEdit {{
    background: {SURFACE}; border: 1px solid {BORDER_STRONG}; border-radius: {RADIUS_SM}px;
    padding: 8px 12px; selection-background-color: {PRIMARY_LIGHT};
    selection-color: {INK}; min-height: 20px;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
QComboBox:focus, QDateEdit:focus {{ border: 1px solid {PRIMARY}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled, QDateEdit:disabled {{
    background: {DISABLED_BG}; color: {DISABLED_TEXT};
}}
QLineEdit[error="true"] {{ border: 1px solid {DANGER}; background: #FEF2F2; }}

QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE}; border: 1px solid {BORDER_STRONG}; border-radius: {RADIUS_SM}px;
    selection-background-color: {PRIMARY_LIGHT}; selection-color: {INK}; padding: 4px;
}}
QSpinBox::up-button, QSpinBox::down-button, QDateEdit::up-button, QDateEdit::down-button {{
    width: 18px; border: none; background: transparent;
}}

QCheckBox {{ spacing: 8px; padding: 4px 0; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 4px;
    border: 2px solid {TEXT_MUTED}; background: {SURFACE};
}}
QCheckBox::indicator:hover {{ border-color: {PRIMARY}; }}
QCheckBox::indicator:checked {{
    background: {PRIMARY_DARK}; border-color: {PRIMARY_DARK};
    __CHECK_IMAGE__
}}
QCheckBox:disabled {{ color: {TEXT_MUTED}; }}
QCheckBox::indicator:disabled {{ border-color: {DISABLED_TEXT}; background: {DISABLED_BG}; }}

QRadioButton {{ spacing: 8px; padding: 4px 0; }}
QRadioButton::indicator {{
    width: 16px; height: 16px; border-radius: 9px;
    border: 2px solid {TEXT_MUTED}; background: {SURFACE};
}}
QRadioButton::indicator:checked {{
    background: {PRIMARY_DARK}; border-color: {PRIMARY_DARK};
    __RADIO_IMAGE__
}}
QRadioButton:disabled {{ color: {TEXT_MUTED}; }}

/* ---------------- tables ---------------- */
QTableWidget, QTableView {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS}px;
    gridline-color: transparent; selection-background-color: {PRIMARY_SOFT};
    selection-color: {INK}; alternate-background-color: #FBFDFF;
}}
QTableWidget::item {{ padding: 6px 8px; border-bottom: 1px solid #F1F5F9; }}
QTableWidget::item:selected {{ background: {PRIMARY_SOFT}; color: {INK}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: #F8FAFC; color: {TEXT_MUTED}; padding: 9px 8px; border: none;
    border-left: 1px solid {BORDER}; border-bottom: 1px solid {BORDER}; font-weight: 600;
}}
QHeaderView::section:first {{ border-top-right-radius: {RADIUS}px; }}
QHeaderView::section:last {{ border-top-left-radius: {RADIUS}px; }}
QTableCornerButton::section {{ background: #F8FAFC; border: none; }}

/* ---------------- scrollbars ---------------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {TEXT_FAINT}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_STRONG}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------------- misc ---------------- */
QProgressBar {{ border: none; background: {BORDER}; border-radius: 4px; height: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 4px; }}

QMenu {{ background: {SURFACE}; border: 1px solid {BORDER_STRONG}; border-radius: {RADIUS_SM}px; padding: 6px; }}
QMenu::item {{ padding: 8px 16px; border-radius: 6px; }}
QMenu::item:selected {{ background: {PRIMARY_SOFT}; color: {PRIMARY_DARK}; }}

QGroupBox {{
    border: 1px solid {BORDER}; border-radius: {RADIUS}px; margin-top: 14px;
    padding: 14px; background: {SURFACE}; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top right; padding: 0 8px; color: {INK}; }}

QSplitter::handle {{ background: {BORDER}; }}
QStackedWidget {{ background: {BACKGROUND}; }}
"""


def apply_theme(app: QApplication) -> None:
    """Apply fonts, RTL layout direction and the global stylesheet."""
    loaded = load_application_fonts()
    family = resolve_font_family(loaded)
    font = QFont(family, BASE_FONT_SIZE)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    # Full RTL everywhere: layout direction, alignment and widget mirroring.
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    app.setStyleSheet(stylesheet(family))


def stylesheet(family: str | None = None) -> str:
    """The global stylesheet, with the resolved Persian font family in place."""
    resolved = family or resolve_font_family()
    check, radio = indicator_images()
    return (_STYLESHEET_TEMPLATE
            .replace("__FONT_FAMILY__", resolved)
            .replace("__CHECK_IMAGE__", f'image: url("{check}");' if check else "")
            .replace("__RADIO_IMAGE__", f'image: url("{radio}");' if radio else ""))


def make_rtl(widget: QWidget) -> QWidget:
    widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    return widget


def app_icon() -> QIcon:
    """The application icon (window title bar and system tray)."""
    from ..paths import assets_dir

    path = assets_dir() / "shopadmin.ico"
    if path.exists():
        return QIcon(str(path))
    return icon("products", 32, PRIMARY)
