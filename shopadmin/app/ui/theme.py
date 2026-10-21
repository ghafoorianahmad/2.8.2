"""Design tokens: palettes, spacing, radii, effects and the global RTL theme.

v2.9.0: three palettes (اقیانوس / شفق / زمرد) in light / dark / follow Windows,
«جلوه‌ها» (auto / full / simple), a gradient side bar, rounded cards and rounded
buttons with soft shadows; generous sizes for readable Persian text.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtCore import QByteArray, QObject, QRectF, Qt
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QWidget

from ..paths import fonts_dir

# --------------------------------------------------------------------------
# palettes (v2.9.0: three looks × light / dark / follow Windows, + «جلوه‌ها»)
#
# Taken from the owner's two other programs:
# * Phone Bridge (E:\Soft\phonebridge\app\theme.py): «ocean» and «emerald», a
#   soft blue-grey window gradient, white cards with large radii, raised buttons
#   with soft (animated) shadows, a deep gradient side bar, and «جلوه‌ها»:
#   full / simple (weak or Remote Desktop PCs get the simple look automatically);
# * the equipment control panel (E:\AsrNetworkProject, v36): «aurora», the
#   indigo → cyan accent with a soft colour glow behind the window, option cards
#   to choose the look, gradient stat icons.
# Every palette shares the neutral base of its mode; only the accent family,
# the side bar and the window tint change. Solid fills that carry WHITE text are
# dark enough for WCAG AA in every palette (scripts/contrast_audit.py --all);
# PRIMARY_TEXT is the accent used AS text on light / dark surfaces.
# --------------------------------------------------------------------------
_BASE: dict[str, dict[str, str]] = {
    "light": {
        "SUCCESS": "#047857", "SUCCESS_DARK": "#065F46", "SUCCESS_LIGHT": "#D1FAE5",
        "WARNING": "#D97706", "WARNING_TEXT": "#92400E", "WARNING_LIGHT": "#FEF3C7",
        "WARNING_BG": "#FFF8E6", "WARNING_BORDER": "#FCD34D",
        "DANGER": "#C5221F", "DANGER_DARK": "#A51B18", "DANGER_LIGHT": "#FDE4E3",
        "INFO": "#0891B2", "INFO_DARK": "#155E75", "INFO_LIGHT": "#CFFAFE",
        "ROLE_PURPLE": "#7B5CF0",
        "INK": "#111827",
        "TEXT": "#1B2230",
        "TEXT_MUTED": "#4E5A6C",       # on white = 7.2:1
        "TEXT_FAINT": "#5B6779",       # on white = 5.9:1
        "BORDER": "#DCE3EE",
        "BORDER_STRONG": "#C3CEDF",
        "SURFACE": "#FFFFFF",
        "BUTTON2": "#E9EEF6",
        "SIDEBAR_OK": "#6EE7B7",
        "SIDEBAR_BAD": "#FCA5A5",
        "ALT_ROW": "#F7F9FD",
        "ROW_LINE": "#EDF1F7",
        "ERROR_BG": "#FEF2F2",
        "DISABLED_BG": "#EEF1F6",
        "DISABLED_TEXT": "#5B6779",
        "SHADOW": "#26304D",
        # v2.9.0: button fills (white text) apart from the same colours used as text
        "SUCCESS_FILL": "#047857", "SUCCESS_FILL_DARK": "#065F46",
        "DANGER_FILL": "#C5221F", "DANGER_FILL_DARK": "#A51B18",
    },
    "dark": {
        # v2.9.0: SUCCESS_DARK / DANGER are mostly TEXT on dark surfaces: light enough
        # to read (the white-text button fills are SUCCESS_FILL / DANGER_FILL)
        "SUCCESS": "#1E7F4E", "SUCCESS_DARK": "#5FD39A", "SUCCESS_LIGHT": "#173A2A",
        "WARNING": "#F0A33A", "WARNING_TEXT": "#F6C67E", "WARNING_LIGHT": "#3A2E17",
        "WARNING_BG": "#2E2515", "WARNING_BORDER": "#7A5A20",
        "DANGER": "#F47A72", "DANGER_DARK": "#A93630", "DANGER_LIGHT": "#3D1F1E",
        "INFO": "#3FC4DE", "INFO_DARK": "#9BE3F1", "INFO_LIGHT": "#173540",
        "ROLE_PURPLE": "#B6A2FF",
        "INK": "#F1F4F9",
        "TEXT": "#E7EBF2",
        "TEXT_MUTED": "#A9B4C6",
        "TEXT_FAINT": "#9AA6B8",
        "BORDER": "#2B3341",
        "BORDER_STRONG": "#3A4456",
        "SURFACE": "#1B212B",
        "BUTTON2": "#212833",
        "SIDEBAR_OK": "#6EE7B7",
        "SIDEBAR_BAD": "#FCA5A5",
        "ALT_ROW": "#1F2631",
        "ROW_LINE": "#262E3A",
        "ERROR_BG": "#3D1F1E",
        "DISABLED_BG": "#232A35",
        "DISABLED_TEXT": "#8D99AB",
        "SHADOW": "#000000",
        "SUCCESS_FILL": "#1E7F4E", "SUCCESS_FILL_DARK": "#176A40",
        "DANGER_FILL": "#C2413A", "DANGER_FILL_DARK": "#A93630",
    },
}

#: palette -> mode -> accent family, side bar and window tint.
_ACCENTS: dict[str, dict[str, dict[str, str]]] = {
    "ocean": {     # Phone Bridge «ocean»
        "light": {
            "PRIMARY": "#1F6AE0", "PRIMARY_DARK": "#1957BF", "PRIMARY_PRESSED": "#14479C",
            "PRIMARY_LIGHT": "#D6E6FD", "PRIMARY_SOFT": "#EAF2FE", "PRIMARY_TEXT": "#1957BF",
            "ACCENT": "#2F7CF6", "ACCENT2": "#1FB5D6",
            "SIDEBAR_BG": "#16325C", "SIDEBAR_BG2": "#0F5A8A", "SIDEBAR_TEXT": "#E9EFFA",
            "SIDEBAR_MUTED": "#B8C8E0", "SIDEBAR_HOVER": "#24477A",
            "SIDEBAR_ACTIVE": "#1F6AE0", "SIDEBAR_ACTIVE2": "#0B7A99",
            "BACKGROUND": "#EEF2F8", "BACKGROUND2": "#E3E9F4", "GLOW": "#DBE7FB",
            "HOVER": "#F1F5FB", "SELECTED_BG": "#EAF2FE", "HEADER_BG": "#EEF2F8",
        },
        "dark": {
            "PRIMARY": "#2F6FD8", "PRIMARY_DARK": "#2A62C0", "PRIMARY_PRESSED": "#22519F",
            "PRIMARY_LIGHT": "#24395E", "PRIMARY_SOFT": "#1E2D47", "PRIMARY_TEXT": "#8DB6FF",
            "ACCENT": "#4E8EF7", "ACCENT2": "#3FC4DE",
            "SIDEBAR_BG": "#0E1A2E", "SIDEBAR_BG2": "#0F3550", "SIDEBAR_TEXT": "#D6DEEB",
            "SIDEBAR_MUTED": "#9FB0C8", "SIDEBAR_HOVER": "#1D2D47",
            "SIDEBAR_ACTIVE": "#2F6FD8", "SIDEBAR_ACTIVE2": "#147A94",
            "BACKGROUND": "#11151C", "BACKGROUND2": "#1A2030", "GLOW": "#17253D",
            "HOVER": "#232B38", "SELECTED_BG": "#1E2D47", "HEADER_BG": "#212833",
        },
    },
    "aurora": {    # the equipment control panel (indigo -> cyan, colour glow)
        "light": {
            "PRIMARY": "#4F46E5", "PRIMARY_DARK": "#4338CA", "PRIMARY_PRESSED": "#3730A3",
            "PRIMARY_LIGHT": "#E0E7FF", "PRIMARY_SOFT": "#EEF2FF", "PRIMARY_TEXT": "#4338CA",
            "ACCENT": "#5A6CFF", "ACCENT2": "#12B5D8",
            "SIDEBAR_BG": "#221E5C", "SIDEBAR_BG2": "#0E4E6E", "SIDEBAR_TEXT": "#ECEBFD",
            "SIDEBAR_MUTED": "#C0C3EE", "SIDEBAR_HOVER": "#332E7E",
            "SIDEBAR_ACTIVE": "#4F46E5", "SIDEBAR_ACTIVE2": "#0E7490",
            "BACKGROUND": "#EEF0FB", "BACKGROUND2": "#E5E8F8", "GLOW": "#E4DDFB",
            "HOVER": "#F2F2FD", "SELECTED_BG": "#EEF2FF", "HEADER_BG": "#EEF0FB",
        },
        "dark": {
            "PRIMARY": "#5850D8", "PRIMARY_DARK": "#4B44C2", "PRIMARY_PRESSED": "#3E37A3",
            "PRIMARY_LIGHT": "#2B2A5E", "PRIMARY_SOFT": "#222248", "PRIMARY_TEXT": "#A5B0FF",
            "ACCENT": "#8B9BFF", "ACCENT2": "#22D3EE",
            "SIDEBAR_BG": "#15123A", "SIDEBAR_BG2": "#0C3247", "SIDEBAR_TEXT": "#DEE0F7",
            "SIDEBAR_MUTED": "#A9AEDB", "SIDEBAR_HOVER": "#26225A",
            "SIDEBAR_ACTIVE": "#5850D8", "SIDEBAR_ACTIVE2": "#0E7490",
            "BACKGROUND": "#0E1020", "BACKGROUND2": "#171A33", "GLOW": "#201C4A",
            "HOVER": "#22253A", "SELECTED_BG": "#222248", "HEADER_BG": "#1F2236",
        },
    },
    "emerald": {   # Phone Bridge «emerald»
        "light": {
            "PRIMARY": "#047857", "PRIMARY_DARK": "#065F46", "PRIMARY_PRESSED": "#064E3B",
            "PRIMARY_LIGHT": "#D1FAE5", "PRIMARY_SOFT": "#ECFDF5", "PRIMARY_TEXT": "#065F46",
            "ACCENT": "#14A37F", "ACCENT2": "#3FC4B0",
            "SIDEBAR_BG": "#0F3B37", "SIDEBAR_BG2": "#11624F", "SIDEBAR_TEXT": "#E6F4EF",
            "SIDEBAR_MUTED": "#B5D6CC", "SIDEBAR_HOVER": "#1A5049",
            "SIDEBAR_ACTIVE": "#047857", "SIDEBAR_ACTIVE2": "#0F766E",
            "BACKGROUND": "#EDF4F1", "BACKGROUND2": "#E2EDE8", "GLOW": "#D4F0E4",
            "HOVER": "#F0F7F4", "SELECTED_BG": "#ECFDF5", "HEADER_BG": "#EDF4F1",
        },
        "dark": {
            "PRIMARY": "#0E8063", "PRIMARY_DARK": "#0B6E55", "PRIMARY_PRESSED": "#095A46",
            "PRIMARY_LIGHT": "#173A30", "PRIMARY_SOFT": "#142E27", "PRIMARY_TEXT": "#5FD4B0",
            "ACCENT": "#2BC49A", "ACCENT2": "#3FC4B0",
            "SIDEBAR_BG": "#0B2622", "SIDEBAR_BG2": "#0E4438", "SIDEBAR_TEXT": "#D5ECE5",
            "SIDEBAR_MUTED": "#9CC4B8", "SIDEBAR_HOVER": "#163A34",
            "SIDEBAR_ACTIVE": "#0E8063", "SIDEBAR_ACTIVE2": "#0F766E",
            "BACKGROUND": "#0D1513", "BACKGROUND2": "#14211E", "GLOW": "#12302A",
            "HOVER": "#1F2B2A", "SELECTED_BG": "#142E27", "HEADER_BG": "#1C2624",
        },
    },
}
PALETTE_NAMES = ("ocean", "aurora", "emerald")
PALETTE_LABELS = {"ocean": "اقیانوس", "aurora": "شفق", "emerald": "زمرد"}
THEME_MODES = ("light", "dark", "system")
MODE_LABELS = {"light": "روشن", "dark": "تیره", "system": "مطابق ویندوز"}
EFFECT_CHOICES = ("auto", "full", "simple")
EFFECT_LABELS = {"auto": "خودکار", "full": "کامل", "simple": "ساده"}


def palette_tokens(palette: str = "ocean", mode: str = "light") -> dict[str, str]:
    """Every colour token of one palette in one mode (``light`` / ``dark``)."""
    mode = mode if mode in _BASE else "light"
    accents = _ACCENTS.get(palette, _ACCENTS["ocean"])
    return {**_BASE[mode], **accents[mode]}


#: v2.7.0 name kept: the «ocean» palette per mode.
PALETTES: dict[str, dict[str, str]] = {m: palette_tokens("ocean", m) for m in ("light", "dark")}

#: The look in use: "light" / "dark", the palette and "full" / "simple" effects.
MODE = "light"
PALETTE = "ocean"
EFFECTS = "full"

PRIMARY = PRIMARY_DARK = PRIMARY_PRESSED = PRIMARY_LIGHT = PRIMARY_SOFT = PRIMARY_TEXT = ""
ACCENT = ACCENT2 = GLOW = SHADOW = ""
SUCCESS = SUCCESS_DARK = SUCCESS_LIGHT = ""
WARNING = WARNING_TEXT = WARNING_LIGHT = WARNING_BG = WARNING_BORDER = ""
DANGER = DANGER_DARK = DANGER_LIGHT = ""
INFO = INFO_DARK = INFO_LIGHT = ""
ROLE_PURPLE = INK = TEXT = TEXT_MUTED = TEXT_FAINT = ""
BORDER = BORDER_STRONG = SURFACE = BACKGROUND = BACKGROUND2 = BUTTON2 = ""
SIDEBAR_BG = SIDEBAR_BG2 = SIDEBAR_TEXT = SIDEBAR_MUTED = SIDEBAR_HOVER = ""
SIDEBAR_ACTIVE = SIDEBAR_ACTIVE2 = SIDEBAR_OK = SIDEBAR_BAD = ""
HOVER = SELECTED_BG = ALT_ROW = ROW_LINE = HEADER_BG = ERROR_BG = ""
DISABLED_BG = DISABLED_TEXT = ""
SUCCESS_FILL = SUCCESS_FILL_DARK = DANGER_FILL = DANGER_FILL_DARK = ""


def resolve_mode(mode: str) -> str:
    if mode in ("light", "dark"):
        return mode
    return "dark" if mode == "system" and system_prefers_dark() else "light"


def set_mode(mode: str, palette: str | None = None) -> str:
    """Load a palette in light or dark into this module (before widgets are made;
    a change shows fully at the next start). Returns the mode used."""
    global MODE, PALETTE
    resolved = resolve_mode(mode)
    if palette in PALETTE_NAMES:
        PALETTE = palette
    globals().update(palette_tokens(PALETTE, resolved))
    MODE = resolved
    if "_ICON_CACHE" in globals():
        _ICON_CACHE.clear()
    return resolved


def system_prefers_dark() -> bool:
    """Windows' «dark» app mode (Qt 6.5+); False when unknown."""
    try:
        from PySide6.QtGui import QGuiApplication

        hints = QGuiApplication.styleHints()
        return bool(hints) and hints.colorScheme() == Qt.ColorScheme.Dark
    except Exception:  # noqa: BLE001 - older Qt / no application yet
        return False


def weak_pc() -> bool:
    """Few cores, little memory or a Remote Desktop session -> simple effects
    (the same rule as Phone Bridge, without psutil)."""
    import os
    import sys

    if (os.cpu_count() or 4) <= 2:
        return True
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        if ctypes.windll.user32.GetSystemMetrics(0x1000):     # SM_REMOTESESSION
            return True

        class _Memory(ctypes.Structure):
            _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        memory = _Memory()
        memory.dwLength = ctypes.sizeof(_Memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            return memory.ullTotalPhys < 4 * 1024 ** 3
    except Exception:  # noqa: BLE001
        return False
    return False


def resolve_effects(effects: str) -> str:
    """auto -> simple on a weak / remote PC, else full."""
    if effects == "auto":
        return "simple" if weak_pc() else "full"
    return effects if effects in ("full", "simple") else "full"


def sidebar_gradient() -> str:
    """The side bar: a vertical gradient in the palette's deep colours."""
    return (f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {SIDEBAR_BG}, "
            f"stop:1 {SIDEBAR_BG2})")


def window_background() -> str:
    """Full effects: a soft colour glow in the top corner over the window
    gradient (the control panel's look); simple: one flat colour."""
    if EFFECTS == "simple":
        return BACKGROUND
    return (f"qradialgradient(cx:0.9, cy:0.0, radius:1.25, fx:0.9, fy:0.0, stop:0 {GLOW}, "
            f"stop:0.55 {BACKGROUND}, stop:1 {BACKGROUND2})")


def shadow_color(alpha: int | None = None) -> QColor:
    color = QColor(SHADOW)
    color.setAlpha(alpha if alpha is not None else (130 if MODE == "dark" else 46))
    return color


globals().update(palette_tokens("ocean", "light"))

# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------
RADIUS_SM = 10
RADIUS = 14          # v2.9.0: rounder buttons (radius never changes a widget's size)
RADIUS_LG = 20
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
    "copy": '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "archive": '<rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',
    "activity": '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
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
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
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


def icon_svg(name: str, color: str | None = None, width: float = 2.0) -> str:
    color = color or TEXT
    body = ICONS.get(name, ICONS["info"])
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{width}" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    )


def icon_pixmap(name: str, size: int = 20, color: str | None = None) -> QPixmap:
    color = color or TEXT
    renderer = QSvgRenderer(QByteArray(icon_svg(name, color).encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


def icon(name: str, size: int = 20, color: str | None = None) -> QIcon:
    color = color or TEXT
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
def _stylesheet_template() -> str:
    # v2.7.0: Phone Bridge look - soft gradient window, rounded white cards,
    # raised buttons with a darker bottom edge, gradient side bar and accents.
    # v2.9.0: three palettes; «ساده» = flat fills (no gradients, no shadows).
    simple = EFFECTS == "simple"
    button_fill = SURFACE if simple else (
        f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {SURFACE}, stop:1 {BUTTON2})")
    primary_fill = PRIMARY if simple else (
        f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {PRIMARY}, stop:1 {PRIMARY_DARK})")
    return f"""
QWidget {{
    font-family: "__FONT_FAMILY__";
    font-size: {BASE_FONT_SIZE}pt;
    color: {TEXT};
}}
QMainWindow, QDialog {{
    background: {window_background()};
}}

QToolTip {{
    background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER_STRONG}; padding: 6px 10px;
    border-radius: {RADIUS_SM}px; font-size: {BASE_FONT_SIZE}pt;
}}

/* ---------------- cards / panels ---------------- */
QFrame#Card {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS_LG}px;
}}
QFrame#Panel {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS_LG}px;
}}
QLabel#CardTitle {{ color: {TEXT_MUTED}; font-size: {BASE_FONT_SIZE}pt; }}
QLabel#CardValue {{ color: {INK}; font-size: 21pt; font-weight: 700; }}
QLabel#PageTitle {{ color: {INK}; font-size: 17pt; font-weight: 700; }}
QLabel#PageSubtitle {{ color: {TEXT_MUTED}; font-size: {BASE_FONT_SIZE}pt; }}
QLabel#PageHelp {{
    color: {TEXT}; background: {PRIMARY_SOFT}; border: 1px solid {BORDER};
    border-radius: {RADIUS}px; padding: 8px 14px;
}}
QLabel#SectionTitle {{ color: {INK}; font-size: 12pt; font-weight: 700; }}
QLabel#Muted {{ color: {TEXT_MUTED}; }}
QLabel#Faint {{ color: {TEXT_FAINT}; }}
QLabel#EmptyTitle {{ color: {TEXT}; font-size: 13pt; font-weight: 700; }}
QLabel#EmptyHint {{ color: {TEXT_MUTED}; }}

/* ---------------- buttons (raised, Phone Bridge) ---------------- */
QPushButton {{
    background: {button_fill};
    color: {TEXT}; border: 1px solid {BORDER_STRONG}; border-bottom: 2px solid {BORDER_STRONG};
    border-radius: {RADIUS}px; padding: 8px 16px; font-size: {BASE_FONT_SIZE}pt;
    min-height: 20px;
}}
QPushButton:hover {{ border-color: {ACCENT}; color: {PRIMARY_TEXT}; }}
QPushButton:pressed {{ background: {BUTTON2}; border-bottom: 1px solid {BORDER_STRONG};
                       padding-top: 9px; padding-bottom: 7px; }}
QPushButton:disabled {{
    background: {DISABLED_BG}; color: {DISABLED_TEXT}; border-color: {BORDER};
}}

QPushButton#Primary {{
    background: {primary_fill};
    color: #FFFFFF; border: none; border-bottom: 3px solid {PRIMARY_PRESSED};
    font-weight: 700; padding: 9px 20px;
}}
QPushButton#Primary:hover {{ background: {PRIMARY_DARK}; color: #FFFFFF; }}
QPushButton#Primary:pressed {{ background: {PRIMARY_PRESSED}; border-bottom: 1px solid {PRIMARY_PRESSED};
                               padding-top: 11px; }}
QPushButton#Primary:disabled {{
    background: {DISABLED_BG}; border: 1px solid {BORDER}; color: {DISABLED_TEXT};
}}

QPushButton#Success {{ background: {SUCCESS_FILL}; color: #FFFFFF; border: none;
                       border-bottom: 3px solid {SUCCESS_FILL_DARK}; font-weight: 700; }}
QPushButton#Success:hover {{ background: {SUCCESS_FILL_DARK}; color: #FFFFFF; }}
QPushButton#Success:disabled {{
    background: {DISABLED_BG}; border: 1px solid {BORDER}; color: {DISABLED_TEXT};
}}

QPushButton#Danger {{ background: {DANGER_FILL}; color: #FFFFFF; border: none;
                      border-bottom: 3px solid {DANGER_FILL_DARK}; font-weight: 700; }}
QPushButton#Danger:hover {{ background: {DANGER_FILL_DARK}; color: #FFFFFF; }}
QPushButton#Danger:disabled {{
    background: {DISABLED_BG}; border: 1px solid {BORDER}; color: {DISABLED_TEXT};
}}

QPushButton#Ghost {{ background: transparent; border: none; color: {TEXT_MUTED}; padding: 6px 10px; }}
QPushButton#Ghost:hover {{ background: {HOVER}; color: {PRIMARY_TEXT}; }}

/* big, clear actions for everyday work (orders) */
QPushButton[big="true"] {{ font-size: 12pt; padding: 12px 22px; min-height: 26px; }}

/* One weight in every state: Qt measures a push button's text with its normal
   font, so a bolder «checked» state used to clip the end of «سفارش‌ها».
   v2.8.1: «text-align» is mirrored in a right-to-left button (like AlignRight,
   see rtl.py): «left» is what puts icon + text against the RIGHT edge. */
QPushButton#NavButton {{
    background: transparent; border: none; border-radius: {RADIUS}px;
    padding: 10px 12px; text-align: left; font-size: 11pt; font-weight: 600;
    color: {SIDEBAR_TEXT};
}}
QPushButton#NavButton:hover {{ background: {SIDEBAR_HOVER}; color: #FFFFFF; }}
QPushButton#NavButton:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {SIDEBAR_ACTIVE}, stop:1 {SIDEBAR_ACTIVE2});
    color: #FFFFFF;
}}
QPushButton#NavButton[hasBadge="true"] {{ color: #FDE68A; }}
QPushButton#NavButton[hasBadge="true"]:checked {{ color: #FFFFFF; }}
QFrame#Sidebar QLabel {{ background: transparent; }}
QLabel#SidebarTitle {{ color: #FFFFFF; font-size: 13pt; font-weight: 700; }}
QLabel#SidebarMuted {{ color: {SIDEBAR_MUTED}; }}

/* v2.9.0: option cards («ظاهر برنامه»): one weight in every state (text fit) */
QPushButton#OptionCard {{
    background: {SURFACE}; color: {TEXT}; border: 2px solid {BORDER}; border-radius: {RADIUS}px;
    padding: 8px 12px; font-weight: 600;
}}
QPushButton#OptionCard:hover {{ border-color: {ACCENT}; color: {TEXT}; }}
QPushButton#OptionCard:checked {{ border: 2px solid {ACCENT}; background: {PRIMARY_SOFT};
                                  color: {PRIMARY_TEXT}; }}

QPushButton#Tab {{
    border: 1px solid transparent; border-radius: {RADIUS_SM}px; padding: 8px 16px;
    background: transparent; color: {TEXT_MUTED}; font-size: {BASE_FONT_SIZE}pt;
    font-weight: 700;
}}
QPushButton#Tab:hover {{ background: {HOVER}; color: {TEXT}; }}
QPushButton#Tab:checked {{ background: {PRIMARY_SOFT}; color: {PRIMARY_TEXT};
                           border: 1px solid {ACCENT}; }}

QPushButton#LinkButton {{
    border: none; background: transparent; color: {PRIMARY_TEXT}; padding: 2px 4px;
    text-decoration: underline; text-align: left;   /* = the right edge in RTL */
}}
QPushButton#LinkButton:hover {{ color: {INK}; }}

QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: {RADIUS}px; background: {SURFACE}; top: -1px; }}
QTabBar::tab {{ background: transparent; padding: 8px 18px; border-radius: {RADIUS_SM}px; margin: 2px;
                color: {TEXT_MUTED}; font-weight: 700; }}
QTabBar::tab:selected {{ background: {PRIMARY_SOFT}; color: {PRIMARY_TEXT}; }}

/* ---------------- inputs ---------------- */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox, QDateEdit {{
    background: {SURFACE}; border: 1px solid {BORDER_STRONG}; border-radius: {RADIUS_SM}px;
    padding: 8px 12px; selection-background-color: {PRIMARY_LIGHT};
    selection-color: {INK}; min-height: 20px;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
QComboBox:focus, QDateEdit:focus {{ border: 2px solid {ACCENT}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled, QDateEdit:disabled {{
    background: {DISABLED_BG}; color: {DISABLED_TEXT};
}}
QLineEdit[error="true"] {{ border: 1px solid {DANGER}; background: {ERROR_BG}; }}

QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE}; border: 1px solid {BORDER_STRONG}; border-radius: {RADIUS_SM}px;
    selection-background-color: {PRIMARY_LIGHT}; selection-color: {INK}; padding: 4px;
}}
QSpinBox::up-button, QSpinBox::down-button, QDateEdit::up-button, QDateEdit::down-button {{
    width: 18px; border: none; background: transparent;
}}

QCheckBox {{ spacing: 8px; padding: 4px 0; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 5px;
    border: 2px solid {TEXT_MUTED}; background: {SURFACE};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
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
QTableWidget, QTableView, QTreeWidget {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS}px;
    gridline-color: transparent; selection-background-color: {SELECTED_BG};
    selection-color: {INK}; alternate-background-color: {ALT_ROW};
}}
QTableWidget::item {{ padding: 6px 8px; border-bottom: 1px solid {ROW_LINE}; }}
QTableWidget::item:selected {{ background: {SELECTED_BG}; color: {INK}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: {HEADER_BG}; color: {TEXT_MUTED}; padding: 9px 10px; border: none;
    border-left: 1px solid {BORDER}; border-bottom: 1px solid {BORDER}; font-weight: 700;
}}
QHeaderView::section:first {{ border-top-right-radius: {RADIUS}px; }}
QHeaderView::section:last {{ border-top-left-radius: {RADIUS}px; }}
QTableCornerButton::section {{ background: {HEADER_BG}; border: none; }}

/* ---------------- scrollbars ---------------- */
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {ACCENT}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_STRONG}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------------- misc ---------------- */
QProgressBar {{ border: none; background: {PRIMARY_SOFT}; border-radius: 7px; min-height: 14px;
                max-height: 14px; text-align: center; }}
QProgressBar::chunk {{ border-radius: 7px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 {ACCENT2}); }}

QMenu {{ background: {SURFACE}; border: 1px solid {BORDER_STRONG}; border-radius: {RADIUS_SM}px; padding: 6px; }}
QMenu::item {{ padding: 8px 16px; border-radius: 6px; }}
QMenu::item:selected {{ background: {PRIMARY_SOFT}; color: {PRIMARY_TEXT}; }}

QGroupBox {{
    border: 1px solid {BORDER}; border-radius: {RADIUS_LG}px; margin-top: 16px;
    padding: 14px; background: {SURFACE}; font-weight: 700;
}}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top right; padding: 2px 10px;
                    color: {PRIMARY_TEXT}; }}

QSplitter::handle {{ background: {BORDER}; }}
QStackedWidget {{ background: transparent; }}
"""


def apply_theme(app: QApplication, mode: str | None = None, *, palette: str | None = None,
                effects: str | None = None) -> str:
    """Apply fonts, RTL layout direction, the palette (v2.9.0: ocean / aurora /
    emerald) in light / dark / system, «جلوه‌ها» (auto / full / simple) and the
    global stylesheet. None keeps the current choice. Returns the effects used."""
    global EFFECTS
    if mode is not None or palette is not None:
        set_mode(mode if mode is not None else MODE, palette)
    if effects is not None:
        EFFECTS = resolve_effects(effects)
    _apply_qt_palette(app)
    loaded = load_application_fonts()
    family = resolve_font_family(loaded)
    font = QFont(family, BASE_FONT_SIZE)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    # Full RTL everywhere: layout direction, alignment and widget mirroring.
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    app.setStyleSheet(stylesheet(family))
    _install_effects(app)
    return EFFECTS


# --------------------------------------------------------------------------
# «جلوه‌ها» (v2.9.0, from Phone Bridge): soft shadows under panels and under the
# main buttons; the buttons' shadow grows on hover and shrinks when pressed.
# --------------------------------------------------------------------------
#: Buttons that get the soft, animated shadow (full effects only).
SHADOW_BUTTONS = ("Primary", "Success", "Danger")


def _inside_item_view(widget: QWidget) -> bool:
    """Cell widgets of tables / lists never get an effect (scrolling cost)."""
    from PySide6.QtWidgets import QAbstractItemView

    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QAbstractItemView):
            return True
        parent = parent.parentWidget()
    return False


def _panel_can_have_shadow(widget: QWidget) -> bool:
    """A graphics effect re-renders everything inside it: only panels without
    tables, lists, text boxes or scroll areas get one."""
    from PySide6.QtWidgets import QAbstractItemView, QAbstractScrollArea

    return not widget.findChildren(QAbstractItemView) and \
        not widget.findChildren(QAbstractScrollArea)


class _Effects(QObject):
    def __init__(self) -> None:
        super().__init__()
        self._anims: dict[int, object] = {}

    def eventFilter(self, obj, event):  # noqa: N802 - Qt naming
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QPushButton

        kind = event.type()
        if kind == QEvent.Type.Polish and isinstance(obj, QWidget) and obj.graphicsEffect() is None:
            name = obj.objectName()
            if isinstance(obj, QPushButton) and name in SHADOW_BUTTONS:
                if not _inside_item_view(obj):
                    _shadow(obj, 12, 3, button=True)
            elif isinstance(obj, QFrame) and name == "Panel" and _panel_can_have_shadow(obj):
                _shadow(obj, 26, 6)
        elif isinstance(obj, QPushButton) and obj.objectName() in SHADOW_BUTTONS and \
                isinstance(obj.graphicsEffect(), QGraphicsDropShadowEffect):
            if kind == QEvent.Type.Enter and obj.isEnabled():
                self._animate(obj, 22, 6)
            elif kind == QEvent.Type.Leave:
                self._animate(obj, 12, 3)
            elif kind == QEvent.Type.MouseButtonPress:
                self._animate(obj, 4, 1, 80)
            elif kind == QEvent.Type.MouseButtonRelease:
                self._animate(obj, 22, 6, 120)
        return False

    def _animate(self, widget, blur: float, dy: float, ms: int = 160) -> None:
        from PySide6.QtCore import QEasingCurve, QPointF, QVariantAnimation

        effect = widget.graphicsEffect()
        old = self._anims.pop(id(widget), None)
        if old is not None:
            old.stop()
        anim = QVariantAnimation(widget)
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(QPointF(effect.blurRadius(), effect.offset().y()))
        anim.setEndValue(QPointF(blur, dy))

        def step(value, effect=effect):
            try:
                effect.setBlurRadius(value.x())
                effect.setOffset(0, value.y())
            except RuntimeError:      # the widget is gone
                pass
        anim.valueChanged.connect(step)
        anim.start()
        self._anims[id(widget)] = anim


def _shadow(widget: QWidget, blur: float, dy: float, *, button: bool = False) -> None:
    from PySide6.QtWidgets import QGraphicsDropShadowEffect

    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(shadow_color(90 if button and MODE != "dark" else None))
    widget.setGraphicsEffect(effect)


_EFFECTS_FILTER: _Effects | None = None


def _install_effects(app: QApplication) -> None:
    global _EFFECTS_FILTER
    from PySide6.QtWidgets import QGraphicsDropShadowEffect

    if _EFFECTS_FILTER is not None:
        app.removeEventFilter(_EFFECTS_FILTER)
        _EFFECTS_FILTER = None
    if EFFECTS == "full":
        _EFFECTS_FILTER = _Effects()
        app.installEventFilter(_EFFECTS_FILTER)
        return
    for widget in app.allWidgets():          # simple: take away the shadows already there
        if isinstance(widget.graphicsEffect(), QGraphicsDropShadowEffect):
            widget.setGraphicsEffect(None)


def _apply_qt_palette(app: QApplication) -> None:
    """Native parts (scroll areas, menus, dialogs) follow the same palette."""
    from PySide6.QtGui import QPalette

    palette = QPalette()
    for role, value in ((QPalette.ColorRole.Window, BACKGROUND),
                        (QPalette.ColorRole.WindowText, TEXT),
                        (QPalette.ColorRole.Base, SURFACE),
                        (QPalette.ColorRole.AlternateBase, ALT_ROW),
                        (QPalette.ColorRole.Text, TEXT),
                        (QPalette.ColorRole.Button, SURFACE),
                        (QPalette.ColorRole.ButtonText, TEXT),
                        (QPalette.ColorRole.Highlight, PRIMARY),
                        (QPalette.ColorRole.HighlightedText, "#FFFFFF"),
                        (QPalette.ColorRole.ToolTipBase, SURFACE),
                        (QPalette.ColorRole.ToolTipText, TEXT),
                        (QPalette.ColorRole.PlaceholderText, TEXT_FAINT)):
        palette.setColor(role, QColor(value))
    app.setPalette(palette)


def stylesheet(family: str | None = None) -> str:
    """The global stylesheet, with the resolved Persian font family in place."""
    resolved = family or resolve_font_family()
    check, radio = indicator_images()
    return (_stylesheet_template()
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
