"""v2.11.0: every site photo in the site's standard — 1280×1024 JPEG, the photo
centred on the site's light background (#FBFCFF, measured on its own photos).

Qt only (``QImage``), so it works the same in the program and in the tests.
"""
from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter

WIDTH, HEIGHT = 1280, 1024
BACKGROUND = "#FBFCFF"
MARGIN = 48
QUALITY = 88
MAX_SOURCE_BYTES = 25 * 1024 * 1024
#: smaller than this on its longest side looks blurry on the site
SMALL_SIDE = 600


class PhotoError(ValueError):
    """A file that is not a usable photo (Persian reason)."""


def load(data: bytes) -> QImage:
    if not data:
        raise PhotoError("فایل عکس خالی است.")
    if len(data) > MAX_SOURCE_BYTES:
        raise PhotoError("عکس بزرگ‌تر از ۲۵ مگابایت است.")
    image = QImage()
    if not image.loadFromData(QByteArray(data)) or image.isNull():
        raise PhotoError("این فایل عکس سالم نیست (jpg، png یا webp بفرستید).")
    return image


def is_standard(image: QImage) -> bool:
    return image.width() == WIDTH and image.height() == HEIGHT


def normalize(data: bytes) -> tuple[bytes, list[str]]:
    """(JPEG bytes in the site standard, Persian notes). A photo that is already
    1280×1024 JPEG is kept byte for byte."""
    image = load(data)
    notes = []
    if max(image.width(), image.height()) < SMALL_SIDE:
        notes.append("عکس کوچک است و در سایت کمی تار دیده می‌شود.")
    if is_standard(image) and data[:2] == b"\xff\xd8":
        return data, notes
    canvas = QImage(WIDTH, HEIGHT, QImage.Format.Format_RGB32)
    canvas.fill(QColor(BACKGROUND))
    scaled = image.scaled(WIDTH - 2 * MARGIN, HEIGHT - 2 * MARGIN,
                          Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
    painter = QPainter(canvas)
    try:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        x = (WIDTH - scaled.width()) // 2
        y = (HEIGHT - scaled.height()) // 2
        painter.drawImage(QRect(x, y, scaled.width(), scaled.height()), scaled)
    finally:
        painter.end()
    return to_jpeg(canvas), notes


def to_jpeg(image: QImage) -> bytes:
    raw = QByteArray()
    buffer = QBuffer(raw)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "JPG", QUALITY)
    buffer.close()
    return bytes(raw.data())


# ---- v2.12.0 «ظاهر و چیدمان»: logo and banner pictures ---------------------------------------
LOGO_SIZE = 256
BANNER_WIDTH, BANNER_HEIGHT = 1200, 600


def to_png(image: QImage) -> bytes:
    raw = QByteArray()
    buffer = QBuffer(raw)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(raw.data())


def normalize_logo(data: bytes) -> bytes:
    """A square 256×256 PNG, the logo centred on a transparent background."""
    image = load(data)
    canvas = QImage(LOGO_SIZE, LOGO_SIZE, QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)
    scaled = image.scaled(LOGO_SIZE, LOGO_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
    painter = QPainter(canvas)
    try:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(QRect((LOGO_SIZE - scaled.width()) // 2,
                                (LOGO_SIZE - scaled.height()) // 2,
                                scaled.width(), scaled.height()), scaled)
    finally:
        painter.end()
    return to_png(canvas)


def normalize_banner(data: bytes) -> tuple[bytes, list[str]]:
    """A 1200×600 JPEG (2:1, like the brand pictures of the banner): the picture
    fills the frame, the middle is kept. Returns (JPEG, Persian notes)."""
    image = load(data)
    notes = []
    if image.width() < BANNER_WIDTH // 2:
        notes.append("عکس بنر کوچک است و در سایت کمی تار دیده می‌شود.")
    scaled = image.scaled(BANNER_WIDTH, BANNER_HEIGHT,
                          Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                          Qt.TransformationMode.SmoothTransformation)
    x = (scaled.width() - BANNER_WIDTH) // 2
    y = (scaled.height() - BANNER_HEIGHT) // 2
    canvas = scaled.copy(x, y, BANNER_WIDTH, BANNER_HEIGHT).convertToFormat(
        QImage.Format.Format_RGB32)
    return to_jpeg(canvas), notes
