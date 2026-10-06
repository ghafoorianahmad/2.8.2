"""ShopSystem launcher - one executable that runs the API and both bots.

What it starts
    1. the shopapi FastAPI service (uvicorn) in a background thread, and
    2. the Bale + Telegram polling loops in an asyncio event loop (own thread).

Where it reads configuration
    `.env` next to the executable (never inside the bundle), plus `app.log` for
    every log line and traceback, so a crash cannot vanish with the console.

Failure isolation
    Each subsystem runs in its own thread with a bounded restart loop: if one
    crashes the launcher logs it and the other keeps working.

This file is packaging glue only - it does not change any business logic or
security feature of `shopapi` / `shopbots`. The few friendly variable names
(SHOPAPI_URL, DB_SERVER, DB_NAME, ...) are translated here into the names those
projects already read.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
from pathlib import Path

BANNER = "ShopSystem is running. Do not close this window. Check app.log for errors."

#: friendly .env name -> the name shopapi / shopbots already read
ALIASES = {
    "SHOPAPI_URL": "SHOPAPI_BASE_URL",
    "DB_SERVER": "ACCOUNTING_SERVER",
    "DB_NAME": "ACCOUNTING_DATABASE",
    "DB_DRIVER": "ACCOUNTING_DRIVER",
    "DB_TRUSTED": "ACCOUNTING_TRUSTED_CONNECTION",
    "DB_USER": "ACCOUNTING_USERNAME",
    "DB_PASSWORD": "ACCOUNTING_PASSWORD",
    "DB_ENCRYPT": "ACCOUNTING_ENCRYPT",
}

logger = logging.getLogger("shopsystem")
_SERVERS: list = []          # running uvicorn servers, so Ctrl+C can stop them
_STOP = threading.Event()


# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------
def app_dir() -> Path:
    """Folder of the .exe when frozen, of this file otherwise."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = app_dir()
ENV_PATH = APP_DIR / ".env"
LOG_PATH = APP_DIR / "app.log"


# --------------------------------------------------------------------------
# logging / crash reporting
# --------------------------------------------------------------------------
def setup_logging(level: str = "INFO") -> None:
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    # httpx logs request URLs at INFO and Bot API URLs contain the token, so
    # those loggers must never reach app.log.
    try:
        from shopbots_app.logging_setup import silence_noisy_loggers

        silence_noisy_loggers()
    except Exception:  # pragma: no cover - never let logging setup break startup
        for name in ("httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.WARNING)


def install_excepthooks() -> None:
    def main_hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        logger.critical("unhandled exception", exc_info=(exc_type, exc, tb))
        print("\n*** Unhandled error - see app.log ***")

    def thread_hook(args) -> None:
        if issubclass(args.exc_type, SystemExit):
            return
        logger.critical(
            "thread %s crashed", getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = main_hook
    threading.excepthook = thread_hook


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------
def load_env_file() -> bool:
    from dotenv import load_dotenv

    if ENV_PATH.exists():
        load_dotenv(ENV_PATH, override=False)
        return True
    return False


def normalise_configuration() -> dict:
    """Translate the friendly names and fill sensible defaults."""
    for friendly, internal in ALIASES.items():
        value = os.environ.get(friendly, "").strip()
        if value and not os.environ.get(internal, "").strip():
            os.environ[internal] = value

    host = os.environ.get("API_HOST", "").strip() or "127.0.0.1"
    try:
        port = int(os.environ.get("API_PORT", "").strip() or 8000)
    except ValueError:
        port = 8000

    # the bots talk to the API served by this same process unless told otherwise
    os.environ.setdefault("SHOPAPI_BASE_URL", f"http://127.0.0.1:{port}")
    # keep the SQLite state files next to the executable, never in the temp bundle
    os.environ.setdefault("SQLITE_PATH", str(APP_DIR / "shopapi.db"))
    os.environ.setdefault("ACCOUNTING_WRITE_ENABLED", "false")

    write_flag = os.environ.get("ACCOUNTING_WRITE_ENABLED", "false").strip().lower()
    return {
        "host": host,
        "port": port,
        "log_level": os.environ.get("LOG_LEVEL", "INFO").strip() or "INFO",
        "write_enabled": write_flag in {"1", "true", "yes", "on"},
        "db_server": os.environ.get("ACCOUNTING_SERVER", ""),
        "db_name": os.environ.get("ACCOUNTING_DATABASE", ""),
        "shopapi_url": os.environ.get("SHOPAPI_BASE_URL", ""),
        "env_found": ENV_PATH.exists(),
    }


# --------------------------------------------------------------------------
# subsystem 1: the API (uvicorn in a background thread)
# --------------------------------------------------------------------------
def start_api(host: str, port: int, max_restarts: int = 5) -> threading.Thread:
    def run() -> None:
        import uvicorn

        from shopapi_app.main import app as asgi_app

        attempt = 0
        while not _STOP.is_set():
            try:
                logger.info("API: starting uvicorn on http://%s:%s", host, port)
                config = uvicorn.Config(
                    asgi_app, host=host, port=port, log_config=None, access_log=True
                )
                server = uvicorn.Server(config)
                _SERVERS.append(server)
                server.run()
                logger.info("API: server stopped")
                return
            except KeyboardInterrupt:
                return
            except BaseException as exc:  # SystemExit included: bad bind, missing DLL, ...
                attempt += 1
                logger.error("API: crashed (%s: %s)", type(exc).__name__, exc)
                logger.debug("API: traceback", exc_info=True)
                if attempt >= max_restarts:
                    logger.error(
                        "API: giving up after %s attempts - the bots keep running", attempt
                    )
                    return
                _STOP.wait(min(5 * attempt, 30))

    thread = threading.Thread(target=run, name="shopapi", daemon=True)
    thread.start()
    return thread


def wait_for_api(url: str, timeout: float = 30.0) -> bool:
    import httpx

    deadline = time.time() + timeout
    health = f"{url.rstrip('/')}/health"
    while time.time() < deadline and not _STOP.is_set():
        try:
            httpx.get(health, timeout=3.0)
            logger.info("API: answering on %s", health)
            return True
        except Exception:
            time.sleep(1.0)
    logger.warning("API: no answer on %s within %.0fs - continuing anyway", health, timeout)
    return False


# --------------------------------------------------------------------------
# subsystem 2: the bots (asyncio loop in a background thread)
# --------------------------------------------------------------------------
def start_bots(max_restarts: int = 10) -> threading.Thread:
    def run() -> None:
        from shopbots_app.config import Settings as BotSettings
        from shopbots_app.main import run as run_bots
        from shopbots_app.store import Store as BotStore

        attempt = 0
        while not _STOP.is_set():
            settings = BotSettings.from_env()
            platforms = settings.enabled_platforms()
            if not platforms:
                logger.warning(
                    "bots: no BALE_TOKEN / TELEGRAM_TOKEN configured - running the API only"
                )
                return
            # the API owns shopapi.db, so the bots keep their own state file
            settings.sqlite_path = str(APP_DIR / "shopbots.db")
            try:
                logger.info("bots: starting %s", ", ".join(platforms))
                store = BotStore(settings.sqlite_path)
                asyncio.run(run_bots(settings, store=store))
                logger.info("bots: stopped")
                return
            except KeyboardInterrupt:
                return
            except BaseException as exc:
                attempt += 1
                logger.error("bots: crashed (%s: %s)", type(exc).__name__, exc)
                logger.debug("bots: traceback", exc_info=True)
                if attempt >= max_restarts:
                    logger.error(
                        "bots: giving up after %s attempts - the API keeps running", attempt
                    )
                    return
                _STOP.wait(min(5 * attempt, 30))

    thread = threading.Thread(target=run, name="shopbots", daemon=True)
    thread.start()
    return thread


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    api_only = "--api-only" in args
    bots_only = "--bots-only" in args

    env_found = load_env_file()
    setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
    install_excepthooks()

    logger.info("=" * 74)
    logger.info("ShopSystem starting  (folder: %s)", APP_DIR)
    logger.info("=" * 74)

    if not env_found:
        logger.error("no .env file found at %s", ENV_PATH)
        logger.error("copy .env.example to .env, fill it in, then start again")
        print()
        print("  ***  .env not found  ***")
        print(f"  1. copy  {ENV_PATH.with_name('.env.example')}")
        print(f"     to    {ENV_PATH}")
        print("  2. fill in the tokens, API keys and database details")
        print("  3. run ShopSystem.exe again")
        _pause()
        return 2

    info = normalise_configuration()
    logger.info("shopapi url : %s", info["shopapi_url"])
    logger.info("database    : server=%r database=%r", info["db_server"], info["db_name"])
    logger.info(
        "real writes : %s", "ENABLED" if info["write_enabled"] else "no (dry run)"
    )
    logger.info("log file    : %s", LOG_PATH)

    api_thread = bots_thread = None
    if not bots_only:
        api_thread = start_api(info["host"], info["port"])
        wait_for_api(info["shopapi_url"])
    if not api_only:
        bots_thread = start_bots()

    print()
    print("=" * 74)
    print(f"  {BANNER}")
    print(f"  API docs : http://{info['host']}:{info['port']}/docs")
    print(f"  Log file : {LOG_PATH}")
    print("=" * 74)
    print()

    try:
        while True:
            alive = [
                t for t in (api_thread, bots_thread) if t is not None and t.is_alive()
            ]
            if not alive:
                logger.error("all subsystems have stopped - nothing left to supervise")
                break
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("shutdown requested (Ctrl+C)")
    finally:
        _STOP.set()
        for server in _SERVERS:
            try:
                server.should_exit = True
            except Exception:
                pass
        for thread in (api_thread, bots_thread):
            if thread is not None:
                thread.join(timeout=10)

    logger.info("ShopSystem stopped")
    print("\nShopSystem stopped. See app.log for details.")
    _pause()
    return 0


def _pause() -> None:
    """Keep a double-clicked console window open."""
    stream = sys.stdin
    if stream is None or not getattr(stream, "isatty", lambda: False)():
        return
    try:
        input("Press Enter to close this window...")
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    raise SystemExit(main())
