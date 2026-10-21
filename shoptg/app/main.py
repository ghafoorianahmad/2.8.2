"""Entry point: ``python -m app.main [--check] [--log-level INFO]``."""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import secure_store
from .config import Settings
from .gateway import TelegramGateway
from .shopapi import ApiError, WorkerApi
from .worker import Worker


def setup_logging(settings: Settings, level: str) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        log_file = Path(settings.log_file) if settings.log_file else settings.data_dir / "shoptg.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(log_file,
                                            maxBytes=2_000_000, backupCount=5, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)
    # Telethon logs connection details at INFO; keep it quiet.
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def make_gateway(settings: Settings, **kwargs) -> TelegramGateway:
    """The gateway with the device parameters of the chosen key (v2.9.0)."""
    return TelegramGateway(settings.api_id, settings.api_hash, timeout=settings.connect_timeout_sec,
                           device=settings.device(), **kwargs)


async def check(settings: Settings) -> int:
    """Configuration report: names and yes/no only, never values."""
    ok = True
    missing = settings.missing()
    print("settings      :", "OK" if not missing else "missing " + ", ".join(missing))
    print("api key       :", "Telegram Desktop (public, temporary)" if settings.api_preset == "tdesktop"
          else "own (my.telegram.org)")
    ok &= not missing
    print("price channel :", "@" + settings.price_channel)
    print("proxy channels:", len(settings.proxy_channels))
    print("local proxies :", len(settings.local_proxies), "(TG_PROXY)")
    print("data folder   :", settings.data_dir)
    try:
        secure_store.load_session(settings.session_file)
        print("session       : present and decryptable")
    except secure_store.SecureStoreError as exc:
        print("session       :", exc)
        ok = False
    api = WorkerApi(settings)
    try:
        state = await api.get_state()
        print("shopapi       : OK (worker key accepted; cursor", state.get("tg_price_last_id") or 0, ")")
    except ApiError as exc:
        print("shopapi       :", exc)
        ok = False
    finally:
        await api.aclose()
    return 0 if ok else 1


async def run(settings: Settings) -> int:
    missing = settings.missing()
    if missing:
        logging.error("missing settings: %s", ", ".join(missing))
        return 2
    api = WorkerApi(settings)
    gateway = make_gateway(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    try:
        await Worker(settings, api, gateway).run(stop)
    finally:
        await api.aclose()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="shoptg")
    parser.add_argument("--login-pipe", action="store_true",
                        help="interactive login over JSON lines on stdin/stdout (ShopAdmin)")
    parser.add_argument("--check", action="store_true", help="report configuration and exit")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if args.login_pipe:
        from .login_flow import run_pipe

        return asyncio.run(run_pipe(settings))
    if args.check:
        return asyncio.run(check(settings))
    setup_logging(settings, args.log_level)
    try:
        return asyncio.run(run(settings))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
