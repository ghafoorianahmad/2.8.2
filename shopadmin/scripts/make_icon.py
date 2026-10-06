"""Generate app/assets/shopadmin.ico without any image library.

An ICO file is a small header followed by PNG-encoded (or BMP) images. We write
PNG entries directly with ``zlib`` so this works before PySide6 is installed.

Usage:
    python scripts/make_icon.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "app" / "assets"

# Calm blue accent used across the UI (theme.PRIMARY = #2563EB).
PRIMARY = (0x25, 0x63, 0xEB, 255)
PRIMARY_DARK = (0x1D, 0x4E, 0xD8, 255)
WHITE = (0xFF, 0xFF, 0xFF, 255)
TRANSPARENT = (0, 0, 0, 0)


def _png(width: int, height: int, pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    raw = b"".join(
        b"\x00" + b"".join(bytes(pixel) for pixel in row) for row in pixels
    )
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _draw(size: int) -> list[list[tuple[int, int, int, int]]]:
    """A rounded blue tile with a white shopfront (awning + door) mark."""
    pixels = [[TRANSPARENT for _ in range(size)] for _ in range(size)]
    radius = size * 0.22

    # --- rounded tile with a soft vertical gradient --------------------
    for y in range(size):
        for x in range(size):
            # Only the four corner boxes need the circular test.
            if x < radius and y < radius:
                inside = (x - radius) ** 2 + (y - radius) ** 2 <= radius ** 2
            elif x >= size - radius and y < radius:
                inside = (x - (size - radius)) ** 2 + (y - radius) ** 2 <= radius ** 2
            elif x < radius and y >= size - radius:
                inside = (x - radius) ** 2 + (y - (size - radius)) ** 2 <= radius ** 2
            elif x >= size - radius and y >= size - radius:
                inside = (
                    (x - (size - radius)) ** 2 + (y - (size - radius)) ** 2 <= radius ** 2
                )
            else:
                inside = True
            if not inside:
                continue
            ratio = y / max(1, size - 1)
            pixels[y][x] = tuple(
                int(PRIMARY[index] * (1 - ratio) + PRIMARY_DARK[index] * ratio)
                for index in range(4)
            )

    def fill(left: float, top: float, right: float, bottom: float) -> None:
        for y in range(int(top), int(bottom)):
            for x in range(int(left), int(right)):
                if 0 <= x < size and 0 <= y < size:
                    pixels[y][x] = WHITE

    # --- awning: a wide rectangle with a scalloped lower edge -----------
    awning_top = size * 0.24
    awning_bottom = size * 0.42
    awning_left = size * 0.18
    awning_right = size * 0.82
    fill(awning_left, awning_top, awning_right, awning_bottom)

    scallop_radius = (awning_right - awning_left) / 8.0
    for index in range(4):
        center_x = awning_left + scallop_radius * (2 * index + 1)
        for y in range(int(awning_bottom - scallop_radius), int(awning_bottom + scallop_radius)):
            for x in range(int(center_x - scallop_radius), int(center_x + scallop_radius) + 1):
                if (x - center_x) ** 2 + (y - awning_bottom) ** 2 <= scallop_radius ** 2:
                    if 0 <= x < size and 0 <= y < size:
                        pixels[y][x] = WHITE
        # Carve the gaps between the scallops back out.
        for y in range(int(awning_bottom), int(awning_bottom + scallop_radius)):
            for x in range(int(center_x + scallop_radius), int(center_x + 2 * scallop_radius)):
                if 0 <= x < size and 0 <= y < size:
                    pixels[y][x] = TRANSPARENT

    # --- body: an outlined shop wall with a door -----------------------
    body_top = awning_bottom + scallop_radius
    body_bottom = size * 0.84
    body_left = size * 0.24
    body_right = size * 0.76
    stroke = max(2, size * 0.055)
    for y in range(int(body_top), int(body_bottom)):
        for x in range(int(body_left), int(body_right)):
            on_border = (
                x < body_left + stroke or x >= body_right - stroke
                or y >= body_bottom - stroke
            )
            if on_border:
                pixels[y][x] = WHITE

    # Door: a solid block on the right half of the wall (RTL-friendly).
    door_left = size * 0.54
    door_right = size * 0.70
    door_top = size * 0.60
    fill(door_left, door_top, door_right, body_bottom)
    return pixels


def build_ico(sizes: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)) -> Path:
    ASSETS.mkdir(parents=True, exist_ok=True)
    images = [(size, _png(size, size, _draw(size))) for size in sizes]

    header = struct.pack("<HHH", 0, 1, len(images))
    entries = b""
    offset = len(header) + 16 * len(images)
    payload = b""
    for size, data in images:
        dimension = 0 if size >= 256 else size
        entries += struct.pack(
            "<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset
        )
        payload += data
        offset += len(data)

    target = ASSETS / "shopadmin.ico"
    target.write_bytes(header + entries + payload)
    print(f"wrote {target} ({target.stat().st_size} bytes, {len(images)} sizes)")
    return target


if __name__ == "__main__":
    build_ico()
