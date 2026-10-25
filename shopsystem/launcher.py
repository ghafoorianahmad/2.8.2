"""Shop server launcher - one executable that runs the API and both bots.

Modes
    ShopSystem.exe              console mode: API + bots in this window (development,
                                or a quick manual run). Closing the window stops it.
    ShopSystem.exe --winservice the Windows service ``ShopServer`` (started by the
                                service control manager at boot): the supervisor.
    ShopSystem.exe --service    the same supervisor from a console / old boot task.
                                It runs the worker and, when ``SHOPTG_DIR`` is set,
                                the Telegram worker; each is restarted on its own
                                when it crashes or asks for a restart.
    ShopSystem.exe --worker     the actual server (started by the supervisor).
    ShopSystem.exe --tg-worker  v2.9.0: the bundled Telegram reader (price lists +
                                proxy pool), started by the supervisor when
                                ``TG_READER_ENABLED=true`` (and no ``SHOPTG_DIR``).
    ShopSystem.exe --tg-login   v2.9.0: Telegram login over JSON lines on
                                stdin/stdout, for «تنظیمات سرور» (administrator).
    ShopSystem.exe --install-service | --uninstall-service | --start-service |
                   --stop-service | --service-status   (administrator; JSON output)
    ShopSystem.exe --health-check [--timeout 90]   wait for /health (update.ps1)
    ShopSystem.exe --fingerprint  print the TLS certificate fingerprint and exit.
    ShopSystem.exe --backup-now               daily backup now (JSON; see backup.py)
    ShopSystem.exe --verify-backup <file>     restore test of a .zip / .ssbk backup
    ShopSystem.exe --decrypt-backup <file.ssbk> --out <file.zip>
    ShopSystem.exe --restore-backup <file>    put a backup back (service stopped;
                                              use deploy\\restore.ps1)
    ShopSystem.exe --set-backup-passphrase    create/enter the off-server passphrase
    The passphrase of a .ssbk comes from SHOPSERVER_BACKUP_PASSPHRASE, else the
    server's .env, else a hidden prompt - never from the command line.

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


def insecure_bind(host: str, tls: bool) -> bool:
    """Listening beyond this computer without TLS."""
    return not tls and host.strip().lower() not in {"127.0.0.1", "localhost", "::1"}


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
    if insecure_bind(host, tls):
        logger.warning("API_HOST=%s without API_TLS: staff passwords and session tokens would "
                       "cross the network in clear text - set API_TLS=true (SECURITY.md)", host)

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
        if all(os.environ.get(k, "").strip()
               for k in ("TELEGRAM_BOT_TOKEN", "TG_API_ID", "TG_API_HASH")):
            configured.append("telegram")
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
    return [*self_command(), "--worker", "--data-dir", str(data_dir)]


def self_command() -> list[str]:
    """How to start this program again (frozen exe, or python + this file)."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, str(Path(__file__).resolve())]


class ChildSpec:
    """One process the supervisor keeps running. ``env_factory`` (v2.9.0) is asked
    for a fresh environment at every start, so a restart sees new settings."""

    def __init__(self, name: str, label: str, command: list[str], *,
                 env: dict, cwd: str | None = None, env_factory=None) -> None:
        self.name, self.label, self.command, self.env, self.cwd = name, label, command, env, cwd
        self.env_factory = env_factory

    def current_env(self) -> dict:
        if self.env_factory is not None:
            try:
                self.env = self.env_factory()
            except Exception as exc:  # noqa: BLE001 - keep the last good environment
                logging.getLogger("shopsystem.supervisor").warning(
                    "%s: settings not re-read (%s)", self.name, type(exc).__name__)
        return self.env


def read_env_values() -> dict[str, str]:
    """``.env`` as a dict, without putting it into this process's environment."""
    if not Paths.env.exists():
        return {}
    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(Paths.env).items() if v is not None}


#: v2.9.0: the server settings the Telegram reader may receive (nothing else:
#: never the Bale / Telegram bot tokens or the database password).
TG_ENV_KEYS = ("TG_API_PRESET", "TG_API_ID", "TG_API_HASH", "TG_PRICE_CHANNEL", "TG_PROXY",
               "TG_PROXY_CHANNELS", "TG_PROXY_POOL_SIZE", "TG_PROXY_COLLECT_HOURS",
               "TG_PROXY_TEST_MAX", "TG_PROXY_WEB_PREVIEW", "TG_ALLOW_DIRECT",
               "TG_DEVICE_MODEL", "TG_SYSTEM_VERSION", "TG_APP_VERSION",
               "TG_PRICE_INTERVAL_MIN")


def tg_reader_enabled(values: dict[str, str]) -> bool:
    return _truthy(values.get("TG_READER_ENABLED", "false"))


def shoptg_env(values: dict[str, str], *, run_mode: str, bundled: bool) -> dict[str, str]:
    """The Telegram reader's environment: the plain system environment plus only
    what it needs from the server: the local API address, the certificate to
    pin, its own key and the ``TG_*`` settings."""
    tls = _truthy(values.get("API_TLS", "false"))
    port = (values.get("API_PORT") or "").strip() or "8000"
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("SHOPSERVER_") and not k.startswith("TG_")}
    env["SHOPAPI_BASE_URL"] = f"{'https' if tls else 'http'}://127.0.0.1:{port}"
    env["WORKER_API_KEY"] = values.get("WORKER_API_KEY", "")
    # v2.8.1 / v2.9.0: the reader's settings come from «تنظیمات سرور»
    for key in TG_ENV_KEYS:
        if (values.get(key) or "").strip():
            env[key] = values[key].strip()
    env["PYTHONIOENCODING"] = "utf-8"
    if tls:
        from server_tls import CERT_NAME

        env["SHOPAPI_CA_FILE"] = str(Paths.tls_dir / CERT_NAME)
    if run_mode == "service":
        from winservice import SERVICE_ACCOUNT

        env["TG_SERVICE_ACCOUNT"] = SERVICE_ACCOUNT
    if bundled:
        env["TG_DATA_DIR"] = str(Paths.data_dir / "shoptg")
        # the service may write here (the session folder is read-only for it)
        env["TG_LOG_FILE"] = str(Paths.data_dir / "shoptg.log")
        env["SHOPTG_NO_DOTENV"] = "1"
    return env


def shoptg_spec(values: dict[str, str], *, run_mode: str) -> ChildSpec | None:
    """The Telegram reader: the old separate install (``SHOPTG_DIR`` = its folder,
    its own Python) or, v2.9.0, the copy bundled in this program
    (``TG_READER_ENABLED=true``)."""
    root = (values.get("SHOPTG_DIR") or "").strip()
    if root:
        python = Path(root) / ".venv" / "Scripts" / "python.exe"
        if not python.exists():
            logging.getLogger("shopsystem.supervisor").warning(
                "SHOPTG_DIR is set but %s is missing - Telegram worker not started", python)
            return None
        env = shoptg_env(values, run_mode=run_mode, bundled=False)
        return ChildSpec("shoptg", "کارگر تلگرام", [str(python), "-m", "app.main"], env=env,
                         cwd=root)
    if not tg_reader_enabled(values):
        return None
    env = shoptg_env(values, run_mode=run_mode, bundled=True)
    return ChildSpec("shoptg", "کارگر تلگرام",
                     [*self_command(), "--tg-worker", "--data-dir", str(Paths.data_dir)], env=env,
                     env_factory=lambda: shoptg_env(read_env_values(), run_mode=run_mode,
                                                    bundled=True))


def _shoptg(module: str):
    """A module of the Telegram reader: ``shoptg_app`` in the build, ``../shoptg/app``
    when run from the source tree."""
    import importlib
    import importlib.util

    if importlib.util.find_spec("shoptg_app") is None and not getattr(sys, "frozen", False):
        root = APP_DIR.parent / "shoptg"
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        return importlib.import_module(f"app.{module}")
    return importlib.import_module(f"shoptg_app.{module}")


def run_tg_worker() -> int:
    """``--tg-worker``: the bundled Telegram reader (its settings come from the
    supervisor; a manual start reads them from the server's ``.env``)."""
    if os.environ.get("SHOPTG_NO_DOTENV") != "1":
        os.environ.update(shoptg_env(read_env_values(), run_mode="task", bundled=True))
    return int(_shoptg("main").main(["--log-level", os.environ.get("LOG_LEVEL", "INFO")]) or 0)


def run_tg_login() -> int:
    """``--tg-login``: the Telegram login of «تنظیمات سرور» (JSON lines on stdin /
    stdout, see shoptg ``login_flow``). The session is readable by the service
    account only when the service exists already (else install grants it)."""
    import winservice

    run_mode = "service" if _service_installed(winservice) else "task"
    os.environ.update(shoptg_env(read_env_values(), run_mode=run_mode, bundled=True))
    return int(_shoptg("main").main(["--login-pipe"]) or 0)


def _service_installed(winservice) -> bool:
    try:
        return bool(winservice.exists())
    except Exception:  # noqa: BLE001 - not Windows / sc.exe missing
        return False


def child_specs(values: dict[str, str], *, run_mode: str) -> list[ChildSpec]:
    env = dict(os.environ, SHOPSERVER_SUPERVISED="1", SHOPSERVER_RUN_MODE=run_mode)
    specs = [ChildSpec("server", "سرور فروشگاه و ربات بله", worker_command(Paths.data_dir), env=env)]
    tg = shoptg_spec(values, run_mode=run_mode)
    if tg is not None:
        specs.append(tg)
    return specs


#: A child that fails this many times within CRASH_WINDOW seconds alerts the owner
#: (at most once per CRASH_ALERT_EVERY seconds per child).
CRASH_COUNT = 3
CRASH_WINDOW = 600
CRASH_ALERT_EVERY = 3600


class CrashTracker:
    def __init__(self, clock=time.monotonic) -> None:
        self.clock = clock
        self.failures: dict[str, list[float]] = {}
        self.alerted: dict[str, float] = {}

    def failed(self, name: str) -> bool:
        """Record a failure; True when the owner should be alerted now."""
        now = self.clock()
        recent = [t for t in self.failures.get(name, []) if now - t < CRASH_WINDOW] + [now]
        self.failures[name] = recent
        if len(recent) < CRASH_COUNT:
            return False
        last = self.alerted.get(name)
        if last is not None and now - last < CRASH_ALERT_EVERY:
            return False
        self.alerted[name] = now
        return True


def crash_alert_text(label: str) -> str:
    return (f"⚠️ هشدار سرور: «{label}» پشت‌سرهم از کار می‌افتد و خودکار دوباره "
            "راه‌اندازی می‌شود. گزارش‌ها: supervisor.log و app.log در پوشهٔ دادهٔ سرور.")


def send_crash_alert(label: str, values: dict[str, str]) -> None:
    try:
        from shopapi_app import owner_alerts
    except ImportError:  # development run without the build packages
        return
    try:
        owner_alerts.send_owner_alert(crash_alert_text(label), env=values)
    except Exception as exc:  # noqa: BLE001 - alerting must never stop supervision
        logging.getLogger("shopsystem.supervisor").warning("crash alert failed (%s)",
                                                           type(exc).__name__)


def supervise_child(spec: ChildSpec, stop: threading.Event, *, job=None,
                    tracker: CrashTracker | None = None, on_crash_loop=None,
                    popen=subprocess.Popen) -> None:
    """Keep one child running until ``stop`` is set (growing back-off on failures)."""
    log = logging.getLogger("shopsystem.supervisor")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    failures = 0
    while not stop.is_set():
        started = time.monotonic()
        try:
            process = popen(spec.command, env=spec.current_env(), cwd=spec.cwd, creationflags=flags,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
        except OSError as exc:
            log.error("%s: cannot start (%s)", spec.name, type(exc).__name__)
            code = None
        else:
            _assign_to_job(job, process)
            log.info("%s started (pid %s)", spec.name, process.pid)
            while process.poll() is None:
                if stop.wait(1.0):
                    log.info("%s: stopping", spec.name)
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    return
            code = process.returncode
            if code == EXIT_RESTART:
                log.info("%s asked for a restart", spec.name)
                failures = 0
                continue
        if time.monotonic() - started > 300:
            failures = 0  # it ran fine for a while: start the back-off over
        failures += 1
        if tracker is not None and tracker.failed(spec.name) and on_crash_loop is not None:
            on_crash_loop(spec)
        delay = 60 if code == EXIT_NO_CONFIG else min(5 * failures, 60)
        log.warning("%s exited with code %s; starting again in %ss", spec.name, code, delay)
        stop.wait(delay)


def run_supervisor(args: list[str], stop_event: threading.Event | None = None) -> int:
    """Run every child until ``stop_event`` is set (Windows service) or Ctrl+C."""
    run_mode = "service" if stop_event is not None else "task"
    stop = stop_event or threading.Event()
    # Its own file: two processes must never rotate the same log.
    setup_logging(os.environ.get("LOG_LEVEL", "INFO"), console=False,
                  log_file=Paths.data_dir / "supervisor.log")
    install_excepthooks()
    supervisor_log = logging.getLogger("shopsystem.supervisor")
    supervisor_log.info("supervisor starting (data folder: %s, mode: %s)", Paths.data_dir, run_mode)
    values = read_env_values()
    job = _kill_on_close_job()
    tracker = CrashTracker()

    def crash_loop(spec: ChildSpec) -> None:
        supervisor_log.error("%s keeps failing - alerting the owner", spec.name)
        threading.Thread(target=send_crash_alert, args=(spec.label, values), daemon=True).start()

    threads = []
    import backup

    threading.Thread(target=backup.scheduler_loop,
                     args=(Paths.data_dir, read_env_values, stop),
                     kwargs={"log": logging.getLogger("shopsystem.backup")},
                     name="backup", daemon=True).start()
    for spec in child_specs(values, run_mode=run_mode):
        thread = threading.Thread(target=supervise_child, args=(spec, stop),
                                  kwargs={"job": job, "tracker": tracker,
                                          "on_crash_loop": crash_loop},
                                  name=f"supervise-{spec.name}", daemon=True)
        thread.start()
        threads.append(thread)
    try:
        while any(t.is_alive() for t in threads):
            if stop.wait(1.0):
                break
    except KeyboardInterrupt:
        stop.set()
    stop.set()
    for thread in threads:
        thread.join(timeout=20)
    supervisor_log.info("supervisor stopped")
    return EXIT_OK


# --------------------------------------------------------------------------
# Windows service management (run as administrator: setup wizard, scripts)
# --------------------------------------------------------------------------
def _shoptg_paths(values: dict[str, str]) -> tuple[Path | None, Path | None]:
    root = (values.get("SHOPTG_DIR") or "").strip()
    return (Path(root) if root else None), Paths.data_dir / "shoptg"


def service_tool(args: list[str]) -> int:
    """``--install-service`` / ``--uninstall-service`` / ``--start-service`` /
    ``--stop-service`` / ``--service-status``: print JSON, exit 0 on success."""
    import winservice

    values = read_env_values()
    shoptg_dir, shoptg_data = _shoptg_paths(values)
    backup_dir = winservice.local_backup_dir(values.get("BACKUP_COPY_DIR"))
    if "--install-service" in args:
        result = winservice.install(self_command(), Paths.data_dir,
                                    shoptg_dir=shoptg_dir, shoptg_data=shoptg_data,
                                    backup_dir=backup_dir)
    elif "--uninstall-service" in args:
        result = winservice.uninstall(Paths.data_dir, shoptg_dir=shoptg_dir,
                                      shoptg_data=shoptg_data, backup_dir=backup_dir)
    elif "--start-service" in args:
        winservice.start()
        result = {"ok": True}
    elif "--stop-service" in args:
        winservice.stop()
        result = {"ok": True}
    else:
        result = {"ok": True}
    result["state"] = winservice.state()
    _emit(result)
    return EXIT_OK


# --------------------------------------------------------------------------
# backups (backup.py; restore.ps1 and the README call these)
# --------------------------------------------------------------------------
PASSPHRASE_ENV = "SHOPSERVER_BACKUP_PASSPHRASE"


def interactive_console() -> bool:
    """A person at a real console (NUL and pipes report isatty() on Windows too)."""
    if sys.stdin is None or not sys.stdin.isatty():
        return False
    if os.name != "nt":
        return True
    import ctypes
    import msvcrt

    try:
        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
    except (OSError, ValueError):
        return False
    mode = ctypes.c_uint32()
    return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))


def _backup_passphrase(values: dict[str, str]) -> str:
    phrase = os.environ.get(PASSPHRASE_ENV, "") or values.get("BACKUP_PASSPHRASE", "")
    if not phrase and interactive_console():
        import getpass

        phrase = getpass.getpass("Backup passphrase (hidden): ")
    if not phrase:
        import backup

        raise backup.BackupError(f"no passphrase: set {PASSPHRASE_ENV} or type it when asked")
    return phrase


def _plain_backup(path: Path, values: dict[str, str], workdir: Path) -> Path:
    """A ``.ssbk`` is decrypted into ``workdir`` first; a ``.zip`` is used as it is."""
    import backup

    if path.suffix.lower() != ".ssbk":
        return path
    plain = workdir / (path.stem + ".zip")
    backup.decrypt_file(path, plain, _backup_passphrase(values))
    return plain


def new_passphrase() -> str:
    """8 groups of 4 from 32 unambiguous capitals/digits = 160 bits."""
    import secrets

    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(8))


def set_backup_passphrase() -> int:
    """Interactive (console, administrator): show a new passphrase once, have the
    owner type it back from paper, then store it in the server's .env."""
    import getpass

    import backup

    if not interactive_console():
        raise backup.BackupError("run this in a console window (it asks questions)")
    if not Paths.env.exists():
        raise backup.BackupError("no .env in the data folder - set up the server first")
    print("A backup passphrase protects the off-server copies. WRITE IT ON PAPER and")
    print("keep the paper away from the server. Without it those copies can NEVER be opened.")
    print(f"Press Enter for a generated one, or type your own ({backup.MIN_PASSPHRASE}+ characters).")
    own = getpass.getpass("Own passphrase (hidden, Enter = generate): ").strip()
    if own:
        problem = backup.passphrase_problem(own)
        if problem:
            raise backup.BackupError(problem)
        phrase = own
    else:
        phrase = new_passphrase()
        print("\n    " + phrase + "\n")
        print("Capital letters and digits only; hyphens and spaces do not matter.")
    again = getpass.getpass("Type it again from your paper (hidden): ")
    if backup.normalise_passphrase(again) != backup.normalise_passphrase(phrase):
        raise backup.BackupError("the two entries differ - nothing was changed")
    from shopapi_app import control

    control.set_files(env_file=Paths.env)
    control.write_env_values({"BACKUP_PASSPHRASE": phrase})
    if os.name == "nt":
        os.system("cls")  # take the passphrase off the screen
    _emit({"ok": True, "message": "passphrase saved in .env (the service reads it at the next backup)"})
    return EXIT_OK


def backup_tool(args: list[str]) -> int:
    import tempfile

    import backup

    values = read_env_values()
    if "--set-backup-passphrase" in args:
        return set_backup_passphrase()
    if "--backup-now" in args:
        status = backup.run_backup(Paths.data_dir, backup.BackupConfig.from_values(values))
        _emit(status)
        return EXIT_OK if status["ok"] else 1
    if "--decrypt-backup" in args:
        source = Path(_arg_value(args, "--decrypt-backup") or "")
        out = Path(_arg_value(args, "--out") or source.with_suffix(".zip"))
        backup.decrypt_file(source, out, _backup_passphrase(values))
        _emit({"ok": True, "out": str(out)})
        return EXIT_OK
    with tempfile.TemporaryDirectory(prefix="shopbak_cli_") as tmp:
        if "--verify-backup" in args:
            plain = _plain_backup(Path(_arg_value(args, "--verify-backup") or ""), values, Path(tmp))
            _emit(backup.verify_backup(plain))
            return EXIT_OK
        source = Path(_arg_value(args, "--restore-backup") or "")
        plain = _plain_backup(source, values, Path(tmp))
        backup.restore_to(plain, Paths.data_dir)
        _emit({"ok": True, "restored": source.name, "data_dir": str(Paths.data_dir)})
        return EXIT_OK


def health_check(timeout: float) -> int:
    """Wait until this server answers ``/health`` (used by update.ps1)."""
    import ssl

    import httpx

    values = read_env_values()
    tls = _truthy(values.get("API_TLS", "false"))
    port = (values.get("API_PORT") or "").strip() or "8000"
    url = f"{'https' if tls else 'http'}://127.0.0.1:{port}/health"
    verify: object = True
    if tls:
        from server_tls import CERT_NAME

        cert = Paths.tls_dir / CERT_NAME
        if not cert.exists():
            _emit({"ok": False, "error": "no certificate yet", "url": url})
            return 1
        verify = ssl.create_default_context(cafile=str(cert))
    deadline = time.monotonic() + timeout
    last = ""
    while True:
        try:
            response = httpx.get(url, timeout=5.0, verify=verify, trust_env=False)
            if response.status_code == 200:
                _emit({"ok": True, "url": url})
                return EXIT_OK
            last = f"HTTP {response.status_code}"
        except Exception as exc:  # noqa: BLE001 - reported as JSON
            last = type(exc).__name__
        if time.monotonic() >= deadline:
            _emit({"ok": False, "error": last, "url": url})
            return 1
        time.sleep(2.0)


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
    "shoptg_dir": "SHOPTG_DIR",
    # v2.8.1: the «تنظیمات سرور» wizard (reopened with the current values)
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    "tg_api_id": "TG_API_ID",
    "tg_api_hash": "TG_API_HASH",
    # v2.9.0: the Telegram reader (price lists + proxy pool), bundled in ShopSystem
    "tg_reader_enabled": "TG_READER_ENABLED",
    "tg_api_preset": "TG_API_PRESET",
    "tg_price_channel": "TG_PRICE_CHANNEL",
    "tg_proxy": "TG_PROXY",
    "firewall_allowed_ips": "FIREWALL_ALLOWED_IPS",
    "allowed_databases": "ACCOUNTING_ALLOWED_DATABASES",
    "write_databases": "ACCOUNTING_WRITE_DATABASES",
    # v2.9.1: the encrypted off-server backup copy («تنظیمات سرور» › شبکه و پشتیبان)
    "backup_copy_dir": "BACKUP_COPY_DIR",
    "backup_passphrase": "BACKUP_PASSPHRASE",
    "backup_keep_days": "BACKUP_KEEP_DAYS",
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
    "PRICE_LEVEL_BOT": "3",      # accessories: gey3 (REQUIREMENTS §4)
    "PRICE_LEVEL_SITE": "3",
    "RECEIPT_DEADLINE_MINUTES": "30",   # receipt within 30 min, then cancelled locally
    "MAX_ORDER_QTY": "10000",
    "ALLOW_SHARED_PERSON_CODE": "false",
    "PENDING_MAX_ORDER_ITEMS": "3",
    "INVOICE_SYNC_SECONDS": "300",
    # ACCOUNTING_STATUS_CODE is deliberately NOT defaulted: 6808 does not exist
    # and the real value comes from GUI test G2. Unset = orders are never committed.
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
    # WORKER_API_KEY: the Telegram worker (shoptg), loopback only.
    for key in ("BOT_API_KEY", "SITE_API_KEY", "ADMIN_API_KEY", "WORKER_API_KEY"):
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
        from shopapi_app.sql_errors import describe

        info = describe(exc)
        message = str(exc).splitlines()[0][:300] if str(exc) else ""
        _emit({"ok": False, "error": type(exc).__name__, "message": message,
               "error_code": info.code, "message_fa": info.message_fa})
        return 1
    _emit({"ok": True, "groups": groups})
    return EXIT_OK


def grant_db() -> int:
    """v2.9.3 «دادن دسترسی به این دیتابیس» (server setup): with the setup's own
    administrator Windows sign-in, give the shop's SQL login (or the service
    account) exactly what grant_shop_app.ps1 gives on the saved database, then
    try the shop's own connection again; print JSON (never the password)."""
    if not load_env_file():
        _emit({"ok": False, "error": "no .env"})
        return EXIT_NO_CONFIG
    normalise_configuration_for_db()
    from shopapi_app.config import Settings
    from shopapi_app.grant_access import GrantError, grant_shop_app

    settings = Settings.from_env()
    try:
        result = grant_shop_app(settings)
    except GrantError as exc:
        _emit({"ok": False, "error": "GrantError", "message_fa": exc.message_fa,
               "message": exc.detail[:300]})
        return 1
    try:
        from shopapi_app.accounting_reader import AccountingReader

        reader = AccountingReader(settings)
        reader.ping()
        result["check_ok"] = True
        result["groups"] = len(reader.list_groups())
    except Exception as exc:  # noqa: BLE001 - reported to the setup screen
        from shopapi_app.sql_errors import describe

        result["check_ok"] = False
        result["check_message_fa"] = describe(exc).message_fa
    _emit(result)
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
    if init_json or "--check-db" in args or "--grant-db" in args:
        # Setup helpers must always answer with JSON, even on failure, so the
        # wizard can show the real reason instead of "unreadable response".
        try:
            if "--grant-db" in args:
                return grant_db()
            return init_config(Path(init_json)) if init_json else check_db()
        except Exception as exc:  # noqa: BLE001 - reported to the setup screen
            text = str(exc).splitlines()[0][:300] if str(exc) else ""
            _emit({"ok": False, "error": type(exc).__name__, "message": f"{type(exc).__name__}: {text}"})
            return 1
    if "--tg-login" in args:
        return run_tg_login()
    if "--tg-worker" in args:
        return run_tg_worker()
    if "--fingerprint" in args:
        from server_tls import ensure_certificate

        _cert, _key, fingerprint = ensure_certificate(Paths.tls_dir)
        print(fingerprint)
        return EXIT_OK
    if "--winservice" in args:
        import winservice

        return winservice.run_service(lambda stop: run_supervisor(args, stop_event=stop))
    if "--service" in args:
        return run_supervisor(args)
    if any(flag in args for flag in SERVICE_FLAGS):
        try:
            return service_tool(args)
        except Exception as exc:  # noqa: BLE001 - always answer with JSON
            text = str(exc).splitlines()[0][:300] if str(exc) else ""
            _emit({"ok": False, "error": type(exc).__name__, "message": text})
            return 1
    if any(flag in args for flag in BACKUP_FLAGS):
        try:
            return backup_tool(args)
        except Exception as exc:  # noqa: BLE001 - always answer with JSON
            import backup

            # only our own messages are shown (restore.ps1 prints them)
            known = isinstance(exc, backup.BackupError)
            text = str(exc).splitlines()[0][:300] if known and str(exc) else ""
            _emit({"ok": False, "error": type(exc).__name__, "message": text})
            return 1
    if "--health-check" in args:
        try:
            timeout = float(_arg_value(args, "--timeout") or 90)
        except ValueError:
            timeout = 90.0
        return health_check(timeout)
    return run_worker(args, console="--worker" not in args)


BACKUP_FLAGS = ("--backup-now", "--verify-backup", "--decrypt-backup", "--restore-backup",
                "--set-backup-passphrase")
SERVICE_FLAGS = ("--install-service", "--uninstall-service", "--start-service",
                 "--stop-service", "--service-status")


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
