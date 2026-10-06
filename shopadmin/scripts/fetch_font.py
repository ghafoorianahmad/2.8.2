"""Download the Vazirmatn Persian font family into app/assets/fonts.

Used at build time only. The application falls back to the Windows system fonts
(Tahoma / Segoe UI) when no bundled font is present, so this step is optional but
recommended: Vazirmatn renders Persian far better than Tahoma.

Usage:
    python scripts/fetch_font.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "app" / "assets" / "fonts"
CURL = r"C:\Windows\System32\curl.exe"

# Vazirmatn ships static TTFs inside the release zip.
RELEASE_API = "https://api.github.com/repos/rastikerdar/vazirmatn/releases/latest"
FALLBACK_TAG = "v33.003"


def curl_json(url: str) -> dict:
    result = subprocess.run(
        [CURL, "-sSL", "--max-time", "60", "-H", "Accept: application/vnd.github+json", url],
        capture_output=True, text=True, errors="replace", timeout=90,
    )
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout)
    except ValueError:
        return {}


def release_zip_url() -> str:
    payload = curl_json(RELEASE_API)
    for asset in payload.get("assets", []):
        name = str(asset.get("name", ""))
        if re.search(r"vazirmatn.*\.zip$", name, re.I):
            return str(asset.get("browser_download_url", ""))
    # Direct URL fallback, so a rate-limited API does not block the build.
    return (
        f"https://github.com/rastikerdar/vazirmatn/releases/download/"
        f"{FALLBACK_TAG}/vazirmatn-{FALLBACK_TAG.lstrip('v')}.zip"
    )


def main() -> int:
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    if list(FONT_DIR.glob("*.ttf")):
        print(f"fonts already present in {FONT_DIR}")
        return 0

    url = release_zip_url()
    archive = FONT_DIR / "_vazirmatn.zip"
    print(f"downloading {url}")
    result = subprocess.run(
        [CURL, "-sSL", "--retry", "3", "--retry-delay", "2", "--max-time", "240",
         "-o", str(archive), url],
        capture_output=True, text=True, errors="replace", timeout=300,
    )
    if result.returncode != 0 or not archive.exists() or archive.stat().st_size < 10_000:
        print("WARNING: could not download Vazirmatn; the app will use system fonts.",
              file=sys.stderr)
        archive.unlink(missing_ok=True)
        return 1

    import zipfile

    wanted = ("Vazirmatn-Regular.ttf", "Vazirmatn-Medium.ttf",
              "Vazirmatn-Bold.ttf", "Vazirmatn-SemiBold.ttf")
    copied = 0
    with zipfile.ZipFile(archive) as zf:
        by_name = {Path(n).name: n for n in zf.namelist()}
        for name in wanted:
            source = by_name.get(name)
            if source is None:
                continue
            with zf.open(source) as src:
                (FONT_DIR / name).write_bytes(src.read())
            copied += 1
    archive.unlink(missing_ok=True)

    if not copied:
        print("WARNING: the archive did not contain the expected fonts.", file=sys.stderr)
        return 1
    print(f"installed {copied} font files into {FONT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
