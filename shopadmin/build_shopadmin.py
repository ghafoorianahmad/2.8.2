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
    # Scientific stack should never be pulled in by a hook. v2.11.0: PIL stays in
    # (pdfplumber needs it for the accessory-PDF reader of the «سایت» section).
    "numpy", "pandas", "matplotlib", "scipy", "tkinter", "unittest",
    "pytest", "setuptools", "pip",
)


#: Left out of the staff-computer (client) build: only the server installer
#: runs the server setup, and the client must carry nothing that knows how to
#: find or start the server program.
SERVER_ONLY_MODULES = ("app.server_setup", "app.ui.server_setup_wizard", "app.ui.telegram_login")


def check_environment() -> None:
    missing: list[str] = []
    for module in ("PySide6", "httpx", "bcrypt", "dotenv", "openpyxl", "pdfplumber"):
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


def build(clean: bool, console: bool, variant: str = "full") -> int:
    check_environment()
    client = variant == "client"
    # The client build gets its own output folders so both builds can coexist.
    dist_dir = DIST_DIR / "client" if client else DIST_DIR
    work_dir = BUILD_DIR / "pyi_client" if client else BUILD_DIR
    spec_dir = BUILD_DIR / "spec_client" if client else ROOT

    if clean:
        targets = (dist_dir / APP_NAME, work_dir) if client else (DIST_DIR / APP_NAME, BUILD_DIR / APP_NAME)
        for path in targets:
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
        "--distpath", str(dist_dir),
        "--workpath", str(work_dir),
        "--specpath", str(spec_dir),
        "--hidden-import", "bcrypt",
        "--hidden-import", "openpyxl",
        "--hidden-import", "PySide6.QtSvg",
        "--hidden-import", "PySide6.QtNetwork",
        "--hidden-import", "PySide6.QtPrintSupport",
        # keyring loads its backends dynamically; without this the frozen build
        # cannot reach the Windows Credential Manager and "remember me" would
        # silently fall back to the local file.
        "--hidden-import", "keyring.backends.Windows",
        "--hidden-import", "keyring.backends.SecretService",
        "--hidden-import", "keyring.backends.kwallet",
        "--hidden-import", "keyring.backends.chainer",
        "--collect-submodules", "keyring",
        "--collect-submodules", "openpyxl",
        # v2.11.0: the accessory-PDF reader of the «سایت» section (runs on this PC)
        "--hidden-import", "pdfplumber",
        "--collect-submodules", "pdfplumber",
        "--collect-submodules", "pdfminer",
        "--collect-data", "pypdfium2_raw",
        "--collect-binaries", "pypdfium2_raw",
        *[f"--exclude-module={module}" for module in EXCLUDED_QT_MODULES],
        *([f"--exclude-module={module}" for module in SERVER_ONLY_MODULES] if client else []),
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

    exe = dist_dir / APP_NAME / f"{APP_NAME}.exe"
    if not exe.exists():
        print(f"BUILD FAILED: {exe} was not produced", file=sys.stderr)
        return 1
    if client:
        leaked = client_build_leaks(dist_dir / APP_NAME)
        if leaked:
            print("BUILD FAILED: the client build still references the server program:",
                  file=sys.stderr)
            for path in leaked:
                print(f"   {path}", file=sys.stderr)
            return 1

    size_mb = sum(f.stat().st_size for f in (dist_dir / APP_NAME).rglob("*") if f.is_file()) / 1e6
    print()
    print("=" * 68)
    print(" BUILD SUCCEEDED")
    print(f"   executable : {exe}")
    print(f"   folder size: {size_mb:.0f} MB")
    print("=" * 68)
    print(" Copy the whole dist\\ShopAdmin folder to the target computer.")
    print(" Python does NOT need to be installed there.")
    return 0


def client_build_leaks(folder: Path) -> list[Path]:
    """Files in a build that mention ``ShopSystem`` (the server program).

    PyInstaller keeps the compiled app modules zlib-compressed inside the PYZ
    archive, so a plain byte search cannot see them; the archive is opened
    and every module is decompressed and searched too.
    """
    needle = b"ShopSystem"
    hits: list[Path] = []
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if needle in data or needle.lower() in data.lower():
            hits.append(path)
    hits += [folder / name for name in _pyz_modules_mentioning(folder, needle)]
    return hits


def _pyz_modules_mentioning(folder: Path, needle: bytes) -> list[str]:
    """Names of modules inside the bundled PYZ archive(s) containing ``needle``."""
    try:
        from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader
    except ImportError:
        return []
    found: list[str] = []
    exe = folder / f"{APP_NAME}.exe"
    archives = [p for p in folder.rglob("*.pyz")]
    try:
        carchive = CArchiveReader(str(exe))
        for name in carchive.toc:
            if name.endswith(".pyz") or name == "PYZ-00.pyz" or name.startswith("PYZ"):
                archives.append((exe, name))
    except Exception:  # noqa: BLE001 - not a PyInstaller exe / layout differs
        pass
    for archive in archives:
        try:
            if isinstance(archive, tuple):
                reader = CArchiveReader(str(archive[0])).open_embedded_archive(archive[1])
            else:
                reader = ZlibArchiveReader(str(archive))
            for name in reader.toc:
                try:
                    code = reader.extract(name, raw=True)
                except TypeError:
                    code = reader.extract(name)
                blob = code if isinstance(code, (bytes, bytearray)) else repr(code).encode()
                if needle in blob or needle.lower() in bytes(blob).lower():
                    found.append(f"PYZ:{name}")
        except Exception:  # noqa: BLE001
            continue
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Build ShopAdmin.exe")
    parser.add_argument("--clean", action="store_true", help="remove the previous build first")
    parser.add_argument("--console", action="store_true",
                        help="keep a console window (useful for troubleshooting)")
    parser.add_argument("--variant", choices=("full", "client"), default="full",
                        help="full = with the server setup (ShopServerSetup); "
                             "client = staff computers, no server setup at all "
                             "(-> dist\\client\\ShopAdmin)")
    args = parser.parse_args()
    try:
        return build(args.clean, args.console, args.variant)
    except SystemExit as exc:  # pragma: no cover
        return int(exc.code or 0)


if __name__ == "__main__":
    raise SystemExit(main())
