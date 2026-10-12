"""Read-only test: fetch the newest PDF of the price channel and parse it.

    .\\check_pricelist.ps1 [-Save] [-Scan 50] [-ProxyChannels]

Works without shopapi (uses the saved session + TG_PROXY or a hidden prompt).
Reads only: no join, no message, nothing marked as read. Nothing secret is
printed (proxies appear as host:port).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import secure_store  # noqa: E402
from app.config import Settings  # noqa: E402
from app.gateway import NotAuthorized, TelegramGateway  # noqa: E402
from app.interactive import (  # noqa: E402
    choose_proxies,
    load_parser,
    require_admin,
    require_api_credentials,
    summarize,
)
from tgproxy import extract_links, parse_proxy_link  # noqa: E402


async def connect(gateway: TelegramGateway, session: str, links) -> bool:
    for link in links:
        where = "via " + link.masked() if link else "directly"
        try:
            ms = await gateway.connect(session, link)
            print(f"Connected {where} ({ms} ms), session is logged in.")
            return True
        except NotAuthorized:
            print("The saved session is not logged in any more: run login.ps1 again.")
            return False
        except Exception as exc:  # noqa: BLE001
            print(f"Could not connect {where}: {type(exc).__name__}")
    return False


async def check(settings: Settings, *, scan: int, save: bool, proxy_channels: bool,
                gateway: TelegramGateway | None = None, session: str | None = None,
                links=None, out=print) -> int:
    parser, pricing = load_parser()
    if session is None:
        session = secure_store.load_session(settings.session_file)
    gateway = gateway or TelegramGateway(settings.api_id, settings.api_hash,
                                         timeout=settings.connect_timeout_sec)
    if links is None:
        links = choose_proxies(settings)
    if not await connect(gateway, session, links):
        return 1
    try:
        channel = settings.price_channel
        messages = await gateway.messages(channel, limit=scan)
        pdfs = [m for m in messages if m.is_pdf]
        out(f"@{channel}: read {len(messages)} newest messages, {len(pdfs)} PDF(s).")
        if not pdfs:
            out("No PDF among them. Try -Scan 200.")
            return 1
        newest = pdfs[-1]
        when = newest.date.isoformat(timespec="minutes") if newest.date else "?"
        out(f"Newest PDF: message {newest.id}, posted {when} UTC, "
            f"{newest.file_size:,} bytes, '{newest.file_name}'")
        data = await gateway.download(newest, settings.pdf_max_bytes)
        if save:
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            target = settings.data_dir / f"check_{newest.id}.pdf"
            target.write_bytes(data)
            out(f"Saved a copy: {target}")
        try:
            parsed = parser.parse_pdf(data)
        except parser.ParseError as exc:
            out(f"PARSE FAILED: {exc}  -> the layout may have changed; keep this PDF for us.")
            return 2
        for line in summarize(parsed, pricing):
            out(line)
        if proxy_channels:
            for name in settings.proxy_channels:
                try:
                    msgs = await gateway.messages(name, limit=100)
                except Exception as exc:  # noqa: BLE001
                    out(f"@{name}: unreadable ({type(exc).__name__})")
                    continue
                found = extract_links([m.text for m in msgs] + [u for m in msgs for u in m.urls])
                kinds = {}
                for raw in found:
                    link = parse_proxy_link(raw)
                    kinds[link.kind] = kinds.get(link.kind, 0) + 1
                out(f"@{name}: {len(msgs)} messages, {len(found)} proxy links {kinds}")
        out("OK: Telegram login, channel access, download and parsing all work.")
        return 0
    finally:
        await gateway.disconnect()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scan", type=int, default=50, help="how many newest messages to look at")
    ap.add_argument("--save", action="store_true", help="keep a copy of the PDF in the data folder")
    ap.add_argument("--proxy-channels", action="store_true",
                    help="also count proxy links in TG_PROXY_CHANNELS")
    args = ap.parse_args()
    require_admin()
    settings = Settings.from_env()
    require_api_credentials(settings)
    try:
        return asyncio.run(check(settings, scan=max(1, min(args.scan, 500)), save=args.save,
                                 proxy_channels=args.proxy_channels))
    except secure_store.SecureStoreError as exc:
        print(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
