"""v2.16.0: REAL browser screenshots of the site, and the live-look check.

The site rule (2.16): the look, layout and structure of the LIVE site
(``origin/main`` of the site repository = asrertebatat2.ir) stays exactly as it
is. This script proves it: it serves the live files and the local files on
127.0.0.1, opens every page in Microsoft Edge (headless, its own empty
profile, reduced motion so the reveal animations do not get in the way) at
desktop and phone width, in the dark and the light theme, takes full-page
screenshots and compares them pixel by pixel.

Usage:
    python scripts/site_compare.py compare <site repo> <out dir> [--ref origin/main]
    python scripts/site_compare.py shot <site folder> <out.png> <page> [--width 1366]
        [--theme dark|light] [--js "<script>"]... [--full]

``compare`` writes ``live_*.png``, ``local_*.png`` and ``diff_*.png`` (changed
pixels in red) and prints one line per page; exit code 1 when any page differs.
``shot`` takes one picture after running the given scripts in the page (for
example a click on an accessory card), so interactive states are real
screenshots too. Nothing is sent anywhere: both servers are 127.0.0.1 only.
"""
from __future__ import annotations

import base64
import functools
import io
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

EDGE = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]
PAGES = ["index.html", "apple.html", "samsung.html", "xiaomi.html",
         "about.html", "contact.html", "404.html"]
WIDTHS = {"desktop": (1366, 900, False), "phone": (390, 844, True)}
THEMES = ["dark", "light"]


# ---- a minimal WebSocket client (enough for the DevTools protocol) ---------------------------
class _WS:
    def __init__(self, url: str) -> None:
        rest = url.split("://", 1)[1]
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                           "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1)
            if not chunk:
                raise ConnectionError("DevTools handshake failed")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError(head.decode(errors="replace"))

    def _read(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(min(n - len(buf), 1 << 20))
            if not chunk:
                raise ConnectionError("DevTools closed the connection")
            buf += chunk
        return bytes(buf)

    def send(self, text: str) -> None:
        data = text.encode()
        head = bytearray([0x81])
        n = len(data)
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head.append(0x80 | 126)
            head += struct.pack(">H", n)
        else:
            head.append(0x80 | 127)
            head += struct.pack(">Q", n)
        mask = os.urandom(4)
        head += mask
        masked = bytes(b ^ mask[i & 3] for i, b in enumerate(data))
        self.sock.sendall(bytes(head) + masked)

    def recv(self) -> str:
        parts = []
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n)
            opcode = b0 & 0x0F
            if opcode == 0x8:
                raise ConnectionError("DevTools closed the connection")
            if opcode in (0x9, 0xA):
                continue
            parts.append(payload)
            if b0 & 0x80:
                return b"".join(parts).decode()


class Browser:
    """Edge headless with its own empty profile, driven over DevTools."""

    def __init__(self) -> None:
        exe = next((p for p in EDGE if Path(p).is_file()), None)
        if not exe:
            raise SystemExit("Microsoft Edge was not found")
        self.profile = tempfile.mkdtemp(prefix="site-shot-")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        self.proc = subprocess.Popen(
            [exe, "--headless=new", f"--remote-debugging-port={port}",
             f"--user-data-dir={self.profile}", "--no-first-run", "--hide-scrollbars",
             "--disable-extensions", "--disable-sync", "--force-color-profile=srgb",
             "--font-render-hinting=none", "--window-size=1366,900", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        target = None
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2) as r:
                    target = next(t for t in json.load(r) if t.get("type") == "page")
                break
            except Exception:
                time.sleep(0.2)
        if not target:
            self.close()
            raise SystemExit("Edge DevTools did not start")
        self.ws = _WS(target["webSocketDebuggerUrl"])
        self._id = 0
        self.call("Page.enable")
        self.call("Runtime.enable")

    def call(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        my = self._id
        self.ws.send(json.dumps({"id": my, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == my:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expr: str):
        res = self.call("Runtime.evaluate", {"expression": expr, "awaitPromise": True,
                                             "returnByValue": True})
        if res.get("exceptionDetails"):
            raise RuntimeError(f"page script failed: {res['exceptionDetails'].get('text')} "
                               f"{res['exceptionDetails'].get('exception', {}).get('description', '')}")
        return res.get("result", {}).get("value")

    def open(self, url: str, width: int, height: int, mobile: bool, theme: str) -> None:
        self.call("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height, "deviceScaleFactor": 1, "mobile": mobile})
        self.call("Emulation.setEmulatedMedia", {"features": [
            {"name": "prefers-reduced-motion", "value": "reduce"}]})
        self.call("Page.navigate", {"url": url})
        self._settle()
        want = theme
        if self.js("document.documentElement.dataset.theme || 'dark'") != want:
            self.js(f"localStorage.setItem('asr-theme', '{want}')")
            self.call("Page.reload", {"ignoreCache": True})
            self._settle()

    def _settle(self) -> None:
        time.sleep(0.3)
        for _ in range(100):
            if self.js("document.readyState") == "complete":
                break
            time.sleep(0.1)
        self.js("document.fonts ? document.fonts.ready.then(() => true) : true")
        time.sleep(3.0)     # catalog.json / site.json wait (2.5 s at most) + photo decode

    def load_images(self) -> None:
        """Every lazy photo loaded and revealed (the same moment on both sides)."""
        self.js("""(async () => {
          document.querySelectorAll('img[loading="lazy"]').forEach(i => { i.loading = 'eager'; });
          const h = document.documentElement.scrollHeight;
          for (let y = 0; y < h; y += 600) { window.scrollTo(0, y); await new Promise(r => setTimeout(r, 60)); }
          window.scrollTo(0, 0);
          await Promise.all([...document.images].map(i => i.complete ? 0 :
            new Promise(r => { i.onload = i.onerror = r; setTimeout(r, 8000); })));
          return true; })()""")
        time.sleep(1.5)

    def shot(self, path: Path, full: bool = True) -> None:
        if full:
            self.load_images()
            h = int(self.js("Math.ceil(document.documentElement.scrollHeight)"))
            w = int(self.js("document.documentElement.clientWidth"))
            clip = {"x": 0, "y": 0, "width": w, "height": min(h, 16000), "scale": 1}
            res = self.call("Page.captureScreenshot", {"format": "png", "clip": clip,
                                                       "captureBeyondViewport": True})
        else:
            res = self.call("Page.captureScreenshot", {"format": "png"})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(res["data"]))

    def close(self) -> None:
        try:
            self.proc.terminate()
            self.proc.wait(10)
        except Exception:
            pass
        shutil.rmtree(self.profile, ignore_errors=True)


# ---- local servers ---------------------------------------------------------------------------
class _Quiet(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *_args) -> None:
        pass


def serve(directory: Path) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(directory)))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def export_ref(repo: Path, ref: str, out: Path) -> None:
    """The files of ``ref`` (git archive; the repository is not touched)."""
    data = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", ref],
                          check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(out, filter="data")


def diff(a: Path, b: Path, out: Path) -> tuple[int, tuple | None, tuple, tuple]:
    from PIL import Image, ImageChops
    ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    size = (max(ia.width, ib.width), max(ia.height, ib.height))
    ca, cb = Image.new("RGB", size, "white"), Image.new("RGB", size, "white")
    ca.paste(ia)
    cb.paste(ib)
    d = ImageChops.difference(ca, cb).convert("L").point(lambda v: 255 if v > 24 else 0)
    changed = d.histogram()[255]
    if changed:
        red = Image.new("RGB", size, (255, 0, 0))
        faded = Image.blend(cb, Image.new("RGB", size, "white"), 0.6)
        faded.paste(red, mask=d)
        out.parent.mkdir(parents=True, exist_ok=True)
        faded.save(out)
    return changed, d.getbbox(), ia.size, ib.size


def compare(repo: Path, out: Path, ref: str, pages: list[str]) -> int:
    live_dir = Path(tempfile.mkdtemp(prefix="site-live-"))
    export_ref(repo, ref, live_dir)
    s1, live_url = serve(live_dir)
    s2, local_url = serve(repo)
    browser = Browser()
    bad = 0
    try:
        for page in pages:
            for wname, (w, h, mobile) in WIDTHS.items():
                for theme in THEMES:
                    tag = f"{page.removesuffix('.html')}_{wname}_{theme}"
                    for side, url in (("live", live_url), ("local", local_url)):
                        browser.open(url + page, w, h, mobile, theme)
                        browser.shot(out / f"{side}_{tag}.png")
                    n, box, sa, sb = diff(out / f"live_{tag}.png", out / f"local_{tag}.png",
                                          out / f"diff_{tag}.png")
                    state = "SAME" if not n else f"DIFF {n} px in {box}"
                    if sa != sb:
                        state += f" (size {sa} -> {sb})"
                    bad += bool(n or sa != sb)
                    print(f"{tag:32} {state}", flush=True)
    finally:
        browser.close()
        s1.shutdown()
        s2.shutdown()
        shutil.rmtree(live_dir, ignore_errors=True)
    print(f"\n{bad} of {len(pages) * len(WIDTHS) * len(THEMES)} differ")
    return 1 if bad else 0


def one_shot(folder: Path, out: Path, page: str, width: int, theme: str,
             scripts: list[str], full: bool) -> int:
    server, url = serve(folder)
    browser = Browser()
    try:
        mobile = width < 700
        browser.open(url + page, width, 844 if mobile else 900, mobile, theme)
        for script in scripts:
            value = browser.js(script)
            if value not in (None, True):
                print(f"script: {value}")
            time.sleep(1.2)
        browser.shot(out, full=full)
    finally:
        browser.close()
        server.shutdown()
    print(out)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 4 and argv[1] == "compare":
        ref = argv[argv.index("--ref") + 1] if "--ref" in argv else "origin/main"
        pages = PAGES
        if "--pages" in argv:
            pages = argv[argv.index("--pages") + 1].split(",")
        return compare(Path(argv[2]), Path(argv[3]), ref, pages)
    if len(argv) >= 5 and argv[1] == "shot":
        width = int(argv[argv.index("--width") + 1]) if "--width" in argv else 1366
        theme = argv[argv.index("--theme") + 1] if "--theme" in argv else "dark"
        scripts = [argv[i + 1] for i, a in enumerate(argv) if a == "--js"]
        return one_shot(Path(argv[2]), Path(argv[3]), argv[4], width, theme, scripts,
                        "--full" in argv)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
