"""v2.12.0 «پیش‌نمایش در مرورگر»: the real site, with the data of THIS computer,
in the computer's own browser — before anything is published.

* **Site code** (the base): the site's own HTML / CSS / JS / fonts / brand
  pictures, from the site folder chosen with «خواندن از پوشهٔ سایت…» or else
  from GitHub (kept in ``<data>/site/site_base`` and refreshed only when a file
  changed).
* **Preview folder** ``<data>/site/preview``: the base + catalog.json, site.json
  and their pictures exactly as «انتشار» would write them.
* **Server**: a tiny web server on 127.0.0.1 only (a random port, this program
  only), because the site reads its files with ``fetch`` (not from ``file://``).

Nothing is sent anywhere; the browser opens ``http://127.0.0.1:<port>/``.
"""
from __future__ import annotations

import functools
import json
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from . import catalog as cat
from . import look as lk
from .github import GitHubPublisher
from .store import SiteDataError, SiteStore, _write_atomic

MAX_FILE = 15 * 1024 * 1024
LOOK_MARKER = b"asr-site-look"


def is_base_file(path: str) -> bool:
    """The files of the site the preview needs (never its product photos or an
    old catalogue: those come from this computer)."""
    parts = path.split("/")
    if len(parts) == 1:
        return path.endswith(".html")
    if parts[0] != "assets" or ".." in parts:
        return False
    if len(parts) == 2:
        return path.endswith((".css", ".js"))
    return parts[1] in ("fonts", "brands")


# ---- the site's own code -------------------------------------------------------------------
def base_from_folder(folder: Path | str) -> Path:
    root = Path(folder)
    if not (root / "index.html").is_file() or not (root / "assets" / "site.js").is_file():
        raise SiteDataError("در پوشهٔ سایت index.html و assets/site.js پیدا نشد.")
    return root


def base_from_github(publisher: GitHubPublisher, cache: Path) -> Path:
    """The site's code from GitHub into ``cache`` (only changed files are read)."""
    remote = {path: sha for path, sha in publisher.tree().items() if is_base_file(path)}
    if "index.html" not in remote:
        raise SiteDataError("در مخزن سایت index.html پیدا نشد.")
    index_path = cache / ".files.json"
    try:
        have = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        have = {}
    for path, sha in sorted(remote.items()):
        if have.get(path) == sha and (cache / path).is_file():
            continue
        data = publisher.read_file(path)
        if data is None or len(data) > MAX_FILE:
            continue
        _write_atomic(cache / path, data)
        have[path] = sha
    for path in [p for p in have if p not in remote]:
        (cache / path).unlink(missing_ok=True)
        have.pop(path)
    _write_atomic(index_path, json.dumps(have).encode("utf-8"))
    return cache


# ---- the preview folder --------------------------------------------------------------------
def build(store: SiteStore, base: Path, out: Path, *, generator: str = "ShopAdmin") -> dict:
    """The preview folder. Returns {"dir", "look_supported", "files"}."""
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    count = 0
    for source in sorted(base.rglob("*")):
        rel = source.relative_to(base).as_posix()
        if source.is_file() and is_base_file(rel) and source.stat().st_size <= MAX_FILE:
            target = out / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            count += 1
    catalog, files = store.build(generator)
    site, look_files = store.build_look(generator)
    for path, source in {**files, **look_files}.items():
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    catalog_dir = out / cat.SITE_CATALOG_DIR
    catalog_dir.mkdir(parents=True, exist_ok=True)
    (catalog_dir / "catalog.json").write_bytes(cat.catalog_bytes(catalog))
    (catalog_dir / lk.LOOK_FILE).write_bytes(lk.site_json_bytes(site))
    site_js = out / "assets" / "site.js"
    supported = site_js.is_file() and LOOK_MARKER in site_js.read_bytes()
    return {"dir": out, "look_supported": supported, "files": count}


# ---- the local web server ------------------------------------------------------------------
class _Handler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *_args) -> None:     # quiet
        pass


class PreviewServer:
    """One server for the program's lifetime; it always serves the newest folder."""

    _lock = threading.Lock()
    _server: Optional[ThreadingHTTPServer] = None
    _thread: Optional[threading.Thread] = None
    _dir: Optional[Path] = None

    @classmethod
    def url(cls, directory: Path) -> str:
        with cls._lock:
            if cls._server is None or cls._dir != Path(directory):
                cls.stop_locked()
                handler = functools.partial(_Handler, directory=str(directory))
                cls._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
                cls._server.daemon_threads = True
                cls._dir = Path(directory)
                cls._thread = threading.Thread(target=cls._server.serve_forever,
                                               name="site-preview", daemon=True)
                cls._thread.start()
            return f"http://127.0.0.1:{cls._server.server_address[1]}/"

    @classmethod
    def stop(cls) -> None:
        with cls._lock:
            cls.stop_locked()

    @classmethod
    def stop_locked(cls) -> None:
        if cls._server is not None:
            cls._server.shutdown()
            cls._server.server_close()
        cls._server = cls._thread = cls._dir = None
