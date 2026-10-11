"""Shop server launcher - one executable that runs the API and both bots.

Modes
    ShopSystem.exe              console mode: API + bots in this window (development,
                                or a quick manual run). Closing the window stops it.
    ShopSystem.exe --service    supervisor: starts a worker process and restarts it
                                when it crashes or when a super admin asks for a
                                restart from ShopAdmin. Used by the Windows
                                scheduled task that starts the server at boot.
    ShopSystem.exe --worker     the actual server (started by the supervisor).
    ShopSystem.exe --fingerprint  print the TLS certificate fingerprint and exit.

Data folder (``.env``, databases, log, TLS certificate)
    --data-dir <folder>  >  SHOPSERVER_DATA_DIR  >  the exe folder when a ``.env``
    is already there (old portable layout)  >  %ProgramData%\\ShopServer.
    Nothing is ever written into the program folder of an installed copy.

Failure isolation
    API and bots run in separate threads with bounded restart loops; the
    supervisor restarts the whole worker with a growing back-off.
"""
from __future__ import annotations

import asyncio
import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

BANNER = "Shop server is running. Do not close this window. Check app.log for errors."

EXIT_OK = 0
EXIT_NO_CONFIG = 2
EXIT_RESTART = 3

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
DEFAULT_DATA_DIR = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "ShopServer"


class Paths:
    data_dir: Path = DEFAULT_DATA_DIR
    env: Path = DEFAULT_DATA_DIR / ".env"
    log: Path = DEFAULT_DATA_DIR / "app.log"
    tls_dir: Path = DEFAULT_DATA_DIR / "tls"


def _arg_value(args: list[str], name: str) -> str | None:
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    for arg in args:
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    return None


def resolve_data_dir(args: list[str]) -> Path:
    explicit = _arg_value(args, "--data-dir") or os.environ.get("SHOPSERVER_DATA_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    if (APP_DIR / ".env").exists():
        return APP_DIR  # old portable layout: keep working where it already lives
    return DEFAULT_DATA_DIR


def configure_paths(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    Paths.data_dir = data_dir
    Paths.env = data_dir / ".env"
    Paths.log = data_dir / "app.log"
    Paths.tls_dir = data_dir / "tls"


# --------------------------------------------------------------------------
# logging / crash reporting
# --------------------------------------------------------------------------
def setup_logging(level: str = "INFO", *, console: bool = True,
                  log_file: Path | None = None) -> None:
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(log_file or Paths.log, maxBytes=5 * 1024 * 1024,
                                             backupCount=5, encoding="utf-8"),
    ]
    if console and sys.stdout is not None:
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

    if Paths.env.exists():
        load_dotenv(Paths.env, override=False)
        return True
    return False


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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

    tls = _truthy(os.environ.get("API_TLS", "false"))
    cert_path = key_path = None
    fingerprint = None
    if tls:
        from server_tls import ensure_certificate

        cert_path, key_path, fingerprint = ensure_certificate(Paths.tls_dir)
        os.environ.setdefault("SHOPAPI_CA_FILE", str(cert_path))
    scheme = "https" if tls else "http"

    # the bots talk to the API served by this same process unless told otherwise
    os.environ.setdefault("SHOPAPI_BASE_URL", f"{scheme}://127.0.0.1:{port}")
    # state files live in the data folder, never in the temp bundle
    os.environ.setdefault("SQLITE_PATH", str(Paths.data_dir / "shopapi.db"))
    os.environ.setdefault("ACCOUNTING_WRITE_ENABLED", "false")

    return {
        "host": host,
        "port": port,
        "tls": tls,
        "cert": cert_path,
        "key": key_path,
        "fingerprint": fingerprint,
        "log_level": os.environ.get("LOG_LEVEL", "INFO").strip() or "INFO",
        "write_enabled": _truthy(os.environ.get("ACCOUNTING_WRITE_ENABLED", "false")),
        "db_server": os.environ.get("ACCOUNTING_SERVER", ""),
        "db_name": os.environ.get("ACCOUNTING_DATABASE", ""),
        "shopapi_url": os.environ.get("SHOPAPI_BASE_URL", ""),
    }


# --------------------------------------------------------------------------
# control hooks (status page, settings, restart) for ShopAdmin
# --------------------------------------------------------------------------
def request_restart() -> None:
    """Exit with EXIT_RESTART; the supervisor starts a fresh worker."""
    logger.info("restart requested by a super admin; exiting for the supervisor")
    for handler in logging.getLogger().handlers:
        try:
            handler.flush()
        except Exception:
            pass
    os._exit(EXIT_RESTART)


def wire_control(info: dict, *, supervised: bool) -> None:
    from shopapi_app import control

    control.set_files(env_file=Paths.env, log_file=Paths.log)
    control.set_tls_fingerprint(info.get("fingerprint"))
    control.set_restart_hook(request_restart if supervised else None)

    def bots_status() -> dict:
        from shopbots_app import health

        configured = ["bale"] if os.environ.get("BALE_TOKEN", "").strip() else []
        return {"configured": configured, "platforms": health.snapshot()}

    control.register_status_provider("bots", bots_status)


# --------------------------------------------------------------------------
# subsystem 1: the API (uvicorn in a background thread)
# --------------------------------------------------------------------------
def start_api(info: dict, max_restarts: int = 5) -> threading.Thread:
    def run() -> None:
        import uvicorn

        from shopapi_app.main import app as asgi_app

        attempt = 0
        scheme = "https" if info["tls"] else "http"
        while not _STOP.is_set():
            try:
                logger.info("API: starting uvicorn on %s://%s:%s", scheme, info["host"], info["port"])
                kwargs = {}
                if info["tls"]:
                    kwargs = {"ssl_certfile": str(info["cert"]), "ssl_keyfile": str(info["key"])}
                config = uvicorn.Config(
                    asgi_app, host=info["host"], port=info["port"], log_config=None,
                    access_log=True, **kwargs,
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
    import ssl

    import httpx

    verify: object = True
    ca_file = os.environ.get("SHOPAPI_CA_FILE", "")
    if ca_file and url.startswith("https"):
        verify = ssl.create_default_context(cafile=ca_file)
    deadline = time.time() + timeout
    health = f"{url.rstrip('/')}/health"
    while time.time() < deadline and not _STOP.is_set():
        try:
            httpx.get(health, timeout=3.0, verify=verify)
            logger.info("API: answering on %s", health)
            return True
        except Exception:
            time.sleep(1.0)
    logger.warning("API: no answer on %s within %.0fs - continuing anyway", health, timeout)
    return False


# --------------------------------------------------------------------------
# subsystem 2: the bots (asyncio loop in a background thread)
# --------------------------------------------------------------------------
MESSAGES_FILE_NAME = "messages.fa.json"


def prepare_messages_file() -> Path | None:
    """The editable bot texts live in the data folder (next to .env).

    On the first start the built-in defaults are copied there; an existing file
    is never overwritten (upgrades only add keys through the built-in defaults).
    """
    from shopbots_app import texts

    target = Paths.data_dir / MESSAGES_FILE_NAME
    try:
        if not target.exists():
            target.write_bytes(texts.DEFAULT_FILE.read_bytes())
            logger.info("bots: wrote default texts to %s (edit, then restart the task)", target)
    except OSError as exc:
        logger.warning("bots: cannot create %s (%s) - using built-in texts", target, type(exc).__name__)
        return None
    os.environ.setdefault("BOT_MESSAGES_FILE", str(target))
    return target


def start_bots(max_restarts: int = 10) -> threading.Thread:
    def run() -> None:
        from shopbots_app import texts
        from shopbots_app.config import Settings as BotSettings
        from shopbots_app.main import run as run_bots
        from shopbots_app.store import Store as BotStore

        attempt = 0
        while not _STOP.is_set():
            settings = BotSettings.from_env()
            platforms = settings.enabled_platforms()
            if not platforms:
                logger.warning(
                    "bots: no BALE_TOKEN configured - running the API only"
                )
                return
            # the API owns shopapi.db, so the bots keep their own state file
            settings.sqlite_path = str(Paths.data_dir / "shopbots.db")
            prepare_messages_file()
            source = texts.load()
            logger.info("bots: texts from %s", source)
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
# worker: API + bots
# --------------------------------------------------------------------------
def run_worker(args: list[str], *, console: bool) -> int:
    api_only = "--api-only" in args
    bots_only = "--bots-only" in args
    supervised = os.environ.get("SHOPSERVER_SUPERVISED") == "1"

    env_found = load_env_file()
    setup_logging(os.environ.get("LOG_LEVEL", "INFO"), console=console)
    install_excepthooks()

    logger.info("=" * 74)
    logger.info("Shop server starting  (data folder: %s, supervised=%s)", Paths.data_dir, supervised)
    logger.info("=" * 74)

    if not env_found:
        logger.error("no .env file found at %s", Paths.env)
        logger.error("run the server setup in ShopAdmin, or copy .env.example to .env")
        if console:
            print()
            print("  ***  .env not found  ***")
            print(f"  expected at: {Paths.env}")
            print("  run the server setup from ShopAdmin on this computer,")
            print("  or copy .env.example there, fill it in and start again.")
            _pause()
        return EXIT_NO_CONFIG

    info = normalise_configuration()
    logger.info("shopapi url : %s", info["shopapi_url"])
    logger.info("listening   : %s:%s (tls=%s)", info["host"], info["port"], info["tls"])
    if info["fingerprint"]:
        logger.info("tls fingerprint (SHA-256): %s", info["fingerprint"])
    logger.info("database    : server=%r database=%r", info["db_server"], info["db_name"])
    logger.info("real writes : %s", "ENABLED" if info["write_enabled"] else "no (dry run)")
    logger.info("log file    : %s", Paths.log)

    wire_control(info, supervised=supervised)

    api_thread = bots_thread = None
    if not bots_only:
        api_thread = start_api(info)
        wait_for_api(info["shopapi_url"])
    if not api_only:
        bots_thread = start_bots()

    if console:
        scheme = "https" if info["tls"] else "http"
        print()
        print("=" * 74)
        print(f"  {BANNER}")
        print(f"  API      : {scheme}://{info['host']}:{info['port']}")
        if info["fingerprint"]:
            print(f"  TLS      : {info['fingerprint']}")
        print(f"  Log file : {Paths.log}")
        print("=" * 74)
        print()

    try:
        while True:
            alive = [t for t in (api_thread, bots_thread) if t is not None and t.is_alive()]
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

    logger.info("Shop server stopped")
    if console:
        print("\nShop server stopped. See app.log for details.")
        _pause()
    return EXIT_OK


# --------------------------------------------------------------------------
# supervisor
# --------------------------------------------------------------------------
def _kill_on_close_job():
    """A Windows Job Object: the worker dies whenever the supervisor dies."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BASIC(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class EXTENDED(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BASIC),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = EXTENDED()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
    return job


def _assign_to_job(job, process: subprocess.Popen) -> None:
    if job is None:
        return
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.AssignProcessToJobObject(job, int(process._handle))  # noqa: SLF001


def worker_command(data_dir: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker", "--data-dir", str(data_dir)]
    return [sys.executable, str(Path(__file__).resolve()), "--worker", "--data-dir", str(data_dir)]


def run_supervisor(args: list[str]) -> int:
    # Its own file: two processes must never rotate the same log.
    setup_logging(os.environ.get("LOG_LEVEL", "INFO"), console=False,
                  log_file=Paths.data_dir / "supervisor.log")
    install_excepthooks()
    supervisor_log = logging.getLogger("shopsystem.supervisor")
    supervisor_log.info("supervisor starting (data folder: %s)", Paths.data_dir)
    job = _kill_on_close_job()
    env = dict(os.environ, SHOPSERVER_SUPERVISED="1")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    failures = 0
    while True:
        started = time.monotonic()
        process = subprocess.Popen(worker_command(Paths.data_dir), env=env, creationflags=flags,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        _assign_to_job(job, process)
        supervisor_log.info("worker started (pid %s)", process.pid)
        try:
            code = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            return EXIT_OK
        if code == EXIT_RESTART:
            supervisor_log.info("worker asked for a restart")
            failures = 0
            continue
        if time.monotonic() - started > 300:
            failures = 0  # it ran fine for a while: start the back-off over
        failures += 1
        delay = 60 if code == EXIT_NO_CONFIG else min(5 * failures, 60)
        supervisor_log.warning("worker exited with code %s; starting again in %ss", code, delay)
        time.sleep(delay)


# --------------------------------------------------------------------------
# setup helpers (used by the server setup in ShopAdmin, run as administrator)
# --------------------------------------------------------------------------
#: init-config JSON field -> .env key
SETUP_FIELDS = {
    "db_server": "DB_SERVER",
    "db_name": "DB_NAME",
    "db_driver": "DB_DRIVER",
    "db_trusted": "DB_TRUSTED",
    "db_user": "DB_USER",
    "db_password": "DB_PASSWORD",
    "api_host": "API_HOST",
    "api_port": "API_PORT",
    "bank_account_text": "BANK_ACCOUNT_TEXT",
    "bale_token": "BALE_TOKEN",
    "admin_chat_ids": "ADMIN_CHAT_IDS",
}

#: Written once, on the first setup. Existing values are never replaced.
FIRST_RUN_DEFAULTS = {
    "API_HOST": "0.0.0.0",
    "API_PORT": "8443",
    "API_TLS": "true",
    "SERVICE_KEYS_LOCAL_ONLY": "true",
    "ACCOUNTING_WRITE_ENABLED": "false",
    "DB_DRIVER": "ODBC Driver 17 for SQL Server",
    "DB_ENCRYPT": "no",
    "PRICE_LEVEL_BOT": "1",
    "PRICE_LEVEL_SITE": "1",
    "RESERVE_HOURS": "12",
    "MAX_ORDER_QTY": "10000",
    "ALLOW_SHARED_PERSON_CODE": "false",
    "ACCOUNTING_STATUS_CODE": "0",   # 6808 does not exist (SAZEH_DB_REFERENCE §9.2)
    "ACCOUNTING_USERCODE": "1",
    "ACCOUNTING_ANBARCODE": "1",
    "LOG_LEVEL": "INFO",
}


def _emit(payload: dict) -> None:
    import json

    print(json.dumps(payload, ensure_ascii=False))


def init_config(json_path: Path) -> int:
    """Create or update ``.env`` from a JSON file, then delete that file.

    The JSON (written by the server setup into the protected data folder)
    carries the database password, so it never appears on a command line.
    New API keys are random and are never printed.
    """
    import json
    import secrets

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    finally:
        try:
            json_path.unlink()
        except OSError:
            pass

    from dotenv import dotenv_values

    existing = {k: v for k, v in dotenv_values(Paths.env).items() if v is not None} \
        if Paths.env.exists() else {}
    values: dict[str, str] = {}
    if not existing:
        values.update(FIRST_RUN_DEFAULTS)
    for key in ("BOT_API_KEY", "SITE_API_KEY", "ADMIN_API_KEY"):
        if not existing.get(key):
            values[key] = secrets.token_urlsafe(32)
    for field, key in SETUP_FIELDS.items():
        if field in data and data[field] is not None:
            value = data[field]
            if isinstance(value, bool):
                value = "yes" if value else "no"
            values[key] = str(value).strip()

    from shopapi_app import control

    control.set_files(env_file=Paths.env)
    if not Paths.env.exists():
        Paths.env.write_text("# Shop server configuration - written by the server setup.\n"
                             "# Keep this folder restricted to Administrators and SYSTEM.\n",
                             encoding="utf-8")
    control.write_env_values(values)
    _emit({"ok": True, "env": str(Paths.env), "created": not existing})
    return EXIT_OK


def check_db() -> int:
    """Try the accounting connection with the saved settings; print JSON."""
    if not load_env_file():
        _emit({"ok": False, "error": "no .env"})
        return EXIT_NO_CONFIG
    normalise_configuration_for_db()
    from shopapi_app.accounting_reader import AccountingReader
    from shopapi_app.config import Settings

    try:
        reader = AccountingReader(Settings.from_env())
        reader.ping()
        groups = len(reader.list_groups())
    except Exception as exc:  # noqa: BLE001 - reported to the setup screen
        message = str(exc).splitlines()[0][:300] if str(exc) else ""
        _emit({"ok": False, "error": type(exc).__name__, "message": message})
        return 1
    _emit({"ok": True, "groups": groups})
    return EXIT_OK


def normalise_configuration_for_db() -> None:
    for friendly, internal in ALIASES.items():
        value = os.environ.get(friendly, "").strip()
        if value and not os.environ.get(internal, "").strip():
            os.environ[internal] = value


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    configure_paths(resolve_data_dir(args))

    init_json = _arg_value(args, "--init-config")
    if init_json or "--check-db" in args:
        # Setup helpers must always answer with JSON, even on failure, so the
        # wizard can show the real reason instead of "unreadable response".
        try:
            return init_config(Path(init_json)) if init_json else check_db()
        except Exception as exc:  # noqa: BLE001 - reported to the setup screen
            text = str(exc).splitlines()[0][:300] if str(exc) else ""
            _emit({"ok": False, "error": type(exc).__name__, "message": f"{type(exc).__name__}: {text}"})
            return 1
    if "--fingerprint" in args:
        from server_tls import ensure_certificate

        _cert, _key, fingerprint = ensure_certificate(Paths.tls_dir)
        print(fingerprint)
        return EXIT_OK
    if "--service" in args:
        return run_supervisor(args)
    return run_worker(args, console="--worker" not in args)


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
