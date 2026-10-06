"""Resolve and download the PySide6 wheels from a PyPI mirror with curl.

Large wheels repeatedly reset through pip's HTTP client on this network, so we
fetch them with resumable curl calls from a mirror and install from the local
folder. Build-time helper only; not part of the shipped application.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parent.parent
WHEEL_DIR = ROOT / ".wheels"
CURL = r"C:\Windows\System32\curl.exe"

MIRRORS = (
    # (index base, file base). Mirrors serve wheels from <file base>/<packages/...>;
    # putting /simple in front of it returns a 404 stub on most of them.
    ("https://pypi.tuna.tsinghua.edu.cn/simple", "https://pypi.tuna.tsinghua.edu.cn"),
    ("https://mirrors.aliyun.com/pypi/simple", "https://mirrors.aliyun.com/pypi"),
    ("https://mirrors.cloud.tencent.com/pypi/simple", "https://mirrors.cloud.tencent.com/pypi"),
    ("https://pypi.org/simple", "https://files.pythonhosted.org"),
)
PACKAGES = ("shiboken6", "PySide6", "PySide6-Essentials")
# Addons (WebEngine, 3D, Charts…) is not imported by ShopAdmin and is skipped,
# which keeps the bundle far smaller.
VERSION = "6.10.3"


def curl(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    # NOTE: no --fail here. The mirror answers a missing path with a 404 body,
    # and we validate the downloaded archive ourselves.
    return subprocess.run(
        [CURL, "-sS", "--retry", "3", "--retry-delay", "2",
         "--connect-timeout", "30", "-m", str(timeout)] + args,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout + 30,
    )


def index_html(index_base: str, package: str) -> str:
    """Fetch the package index, trying both ``-`` and ``_`` spellings."""
    for name in dict.fromkeys((package.lower(), package.lower().replace("-", "_"))):
        result = curl([f"{index_base}/{name}/"], timeout=60)
        if result.returncode == 0 and "<a " in result.stdout:
            return result.stdout
    return ""


def find_wheels(index_base: str, file_base: str, package: str, version: str) -> list[str]:
    """Return candidate wheel URLs for a package version."""
    html = index_html(index_base, package)
    if not html:
        return []
    # The wheel filename may use "-" or "_" where the package name has one.
    name_pattern = re.escape(package.lower()).replace(r"\-", r"[-_]")
    pattern = re.compile(
        r'href="([^"#]*?/packages/[^"#]*' + name_pattern + r'-'
        + re.escape(version) + r'-[^"#]*win_amd64\.whl)[^"]*"'
    )
    candidates: list[str] = []
    for match in pattern.finditer(html):
        href = match.group(1)
        path = href[href.index("/packages/"):]
        for base in (file_base, index_base.rsplit("/simple", 1)[0]):
            url = f"{base}{path}"
            if url not in candidates:
                candidates.append(url)
    return candidates


def download(url: str, attempts: int = 40) -> Path:
    """Fetch one URL with resume until it stops growing for good.

    These mirrors reset long connections every ~60-120 s, so a single wheel may
    need many resumes; give up only after several attempts with no progress.
    """
    name = url.split("/")[-1]
    target = WHEEL_DIR / name
    previous = -1
    stalled = 0
    best = 0
    print(f"  downloading {name}", flush=True)
    for attempt in range(1, attempts + 1):
        size = target.stat().st_size if target.exists() else 0
        if size < 10_000:
            # A tiny file is an error body, not a partial download: never resume it.
            target.unlink(missing_ok=True)
            size = 0
        print(f"    [{attempt}] {size / 1048576:.1f} MB", flush=True)
        if size > best:
            best = size
            stalled = 0
        else:
            stalled += 1
            if stalled >= 6:
                print("    no progress for 6 attempts; stopping", flush=True)
                break
        result = curl([
            "-L", "--retry", "5", "--retry-delay", "2", "--max-time", "240",
            "-C", "-", "-o", str(target), url,
        ], timeout=300)
        if result.returncode != 0:
            print(f"      curl rc={result.returncode} {result.stderr.strip()[:90]}", flush=True)
    print(f"    final {target.stat().st_size / 1048576:.1f} MB", flush=True)
    return target


def is_usable(wheel: Path) -> bool:
    """A wheel must be a ZIP archive that really contains the package files."""
    if not wheel.exists() or wheel.stat().st_size < 200_000:
        return False
    try:
        import zipfile

        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
        return any(name.endswith(".dist-info/RECORD") for name in names) and any(
            name.endswith((".pyd", ".py", ".dll")) for name in names
        )
    except Exception:
        return False


def main() -> int:
    WHEEL_DIR.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    for package in PACKAGES:
        candidates: list[str] = []
        for index_base, file_base in MIRRORS:
            print(f"resolving {package} from {index_base}", flush=True)
            candidates = find_wheels(index_base, file_base, package, VERSION)
            if candidates:
                break
        if not candidates:
            print(f"[FAIL] could not resolve {package}", flush=True)
            failures.append(package)
            continue

        print(f"  {len(candidates)} candidate URL(s)", flush=True)
        done = False
        for url in candidates:
            wheel = download(url)
            if is_usable(wheel):
                print(f"  [ok] {wheel.name} {wheel.stat().st_size / 1048576:.1f} MB", flush=True)
                done = True
                break
            print("  unusable archive; trying the next candidate", flush=True)
            wheel.unlink(missing_ok=True)
        if not done:
            print(f"[FAIL] no usable wheel for {package}", flush=True)
            failures.append(package)

    print("downloads finished", flush=True)
    for wheel in sorted(WHEEL_DIR.glob("*.whl")):
        print(f"  {wheel.name}  {wheel.stat().st_size / 1048576:.1f} MB", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
