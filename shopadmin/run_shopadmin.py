"""Executable entry point for ShopAdmin.

Kept at the project root so PyInstaller has a simple, stable target:

    python run_shopadmin.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the project root is importable when launched by path.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# High-DPI friendly defaults for Qt on Windows.
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")


def main() -> int:
    from app.main import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
