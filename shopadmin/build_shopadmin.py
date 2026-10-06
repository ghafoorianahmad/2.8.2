"""PyInstaller build for ShopAdmin (Persian desktop admin console).

Produces a --onedir bundle, which starts faster and is far more reliable than
--onefile for a Qt application:

    dist/ShopAdmin/ShopAdmin.exe

Usage:
    python build_shopadmin.py [--clean] [--console]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "ShopAdmin"
ENTRY = ROOT / "run_shopadmin.py"
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
SPEC_FILE = ROOT / f"{APP_NAME}.spec"

# Qt modules ShopAdmin imports. Excluding the rest keeps the bundle ~40% smaller.
EXCLUDED_QT_MODULES = (
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml", "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DAnimation",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtSerialPort", "PySide6.QtSerialBus", "PySide6.QtSensors",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtTest", "PySide6.QtSql",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtTextToSpeech", "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "shiboken6.support",
    # Scientific stack should never be pulled in by a hook.
    "numpy", "pandas", "matplotlib", "scipy", "PIL", "tkinter", "unittest",
    "pytest", "setuptools", "pip",
)


def check_environment() -> None:
    missing: list[str] = []
    for module in ("PySide6", "httpx", "bcrypt", "dotenv", "openpyxl"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    if missing:
        print("ERROR: missing dependencies: " + ", ".join(missing), file=sys.stderr)
        print("Install them first:  pip install -r requirements.txt", file=sys.stderr)
        raise SystemExit(2)
    try:
        import keyring  # noqa: F401
    except ImportError:
        print("WARNING: 'keyring' is not installed. «مرا به خاطر بسپار» will fall "
              "back to the obfuscated local file instead of the Windows "
              "Credential Manager.", file=sys.stderr)
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("ERROR: PyInstaller is not installed.  pip install pyinstaller", file=sys.stderr)
        raise SystemExit(2)


def assets_exist() -> bool:
    assets = ROOT / "app" / "assets"
    if not assets.exists():
        return False
    return any(assets.rglob("*"))


def build(clean: bool, console: bool) -> int:
    check_environment()

    if clean:
        for path in (DIST_DIR, BUILD_DIR):
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
                print(f"removed {path}")

    add_data: list[str] = []
    assets = ROOT / "app" / "assets"
    if assets_exist():
        separator = ";" if sys.platform.startswith("win") else ":"
        add_data += ["--add-data", f"{assets}{separator}app/assets"]
        print(f"bundling assets from {assets}")
    else:
        print("WARNING: app/assets not found; the app will fall back to a system font.")

    for extra in (ROOT / ".env.example", ROOT / "README.txt"):
        if extra.exists():
            separator = ";" if sys.platform.startswith("win") else ":"
            add_data += ["--add-data", f"{extra}{separator}."]

    icon = ROOT / "app" / "assets" / "shopadmin.ico"
    icon_args = ["--icon", str(icon)] if icon.exists() else []

    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name", APP_NAME,
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--specpath", str(ROOT),
        "--hidden-import", "bcrypt",
        "--hidden-import", "openpyxl",
        "--hidden-import", "PySide6.QtSvg",
        "--hidden-import", "PySide6.QtNetwork",
        # keyring loads its backends dynamically; without this the frozen build
        # cannot reach the Windows Credential Manager and "remember me" would
        # silently fall back to the local file.
        "--hidden-import", "keyring.backends.Windows",
        "--hidden-import", "keyring.backends.SecretService",
        "--hidden-import", "keyring.backends.kwallet",
        "--hidden-import", "keyring.backends.chainer",
        "--collect-submodules", "keyring",
        "--collect-submodules", "openpyxl",
        *[f"--exclude-module={module}" for module in EXCLUDED_QT_MODULES],
        *add_data,
        *icon_args,
        ("--console" if console else "--windowed"),
        str(ENTRY),
    ]

    print("running:", " ".join(command[:6]), "...")
    result = subprocess.run(command, cwd=str(ROOT))
    if result.returncode != 0:
        print("BUILD FAILED", file=sys.stderr)
        return result.returncode

    exe = DIST_DIR / APP_NAME / f"{APP_NAME}.exe"
    if not exe.exists():
        print(f"BUILD FAILED: {exe} was not produced", file=sys.stderr)
        return 1

    size_mb = sum(f.stat().st_size for f in (DIST_DIR / APP_NAME).rglob("*") if f.is_file()) / 1e6
    print()
    print("=" * 68)
    print(" BUILD SUCCEEDED")
    print(f"   executable : {exe}")
    print(f"   folder size: {size_mb:.0f} MB")
    print("=" * 68)
    print(" Copy the whole dist\\ShopAdmin folder to the target computer.")
    print(" Python does NOT need to be installed there.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build ShopAdmin.exe")
    parser.add_argument("--clean", action="store_true", help="remove build/ and dist/ first")
    parser.add_argument("--console", action="store_true",
                        help="keep a console window (useful for troubleshooting)")
    args = parser.parse_args()
    try:
        return build(args.clean, args.console)
    except SystemExit as exc:  # pragma: no cover
        return int(exc.code or 0)


if __name__ == "__main__":
    raise SystemExit(main())
