"""Server setup on the server computer itself (run as administrator).

What it does, in order — each step is a small function so the wizard can show
progress and stop on the first problem:

1. lock the data folder (%ProgramData%\\ShopServer) to SYSTEM + Administrators,
2. write ``.env`` through ``ShopSystem.exe --init-config`` (random API keys;
   the database password travels in a JSON file inside the locked folder,
   never on a command line, and the file is deleted right away),
3. test the accounting connection with ``ShopSystem.exe --check-db``,
4. register the Windows service ``ShopServer`` (virtual account
   ``NT SERVICE\\ShopServer``, starts at boot, restarts on failure; the old
   scheduled task is removed) plus a firewall rule for the local network only
   (or an explicit list of client addresses),
5. start it, wait for HTTPS, pin its certificate (read from the local file —
   no trust-on-first-use needed on the server itself),
6. create the first super admin with the server-local service key.

Nothing here is reachable from the network; it needs a local administrator.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .errors import SetupError
from .logging_setup import get_logger
from .paths import app_dir, is_frozen

log = get_logger("server_setup")

FIREWALL_RULE = "ShopServer"
DEFAULT_PORT = 8443
SID_SYSTEM = "S-1-5-18"
SID_ADMINISTRATORS = "S-1-5-32-544"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


__all__ = ["SetupError"]


def data_dir() -> Path:
    return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "ShopServer"


# --------------------------------------------------------------------------
# elevation
# --------------------------------------------------------------------------
def is_admin() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001 - non-Windows
        return False


def relaunch_elevated(extra_args: list[str]) -> bool:
    """Start this program again with a UAC prompt. True when the prompt was shown."""
    import ctypes

    if is_frozen():
        program, args = sys.executable, extra_args
    else:
        program, args = sys.executable, [str(app_dir() / "run_shopadmin.py"), *extra_args]
    params = subprocess.list2cmdline(args)
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", program, params, None, 1)
    return int(result) > 32


# --------------------------------------------------------------------------
# the server program
# --------------------------------------------------------------------------
SERVER_EXE_NAME = "ShopSystem.exe"


def find_server_executable() -> Optional[Path]:
    """The server installer's layout: ``{app}\\ShopSystem\\ShopSystem.exe``.

    Only the server setup (``--server-setup``, run by ShopServerSetup) uses
    this; the everyday management console never looks for the server program.
    """
    here = app_dir()
    roots = [here, here / "ShopSystem", here.parent / "ShopSystem"]
    if not is_frozen():
        roots.append(here.parent / "shopsystem" / "dist" / "ShopSystem")
    for root in roots:
        candidate = root / SERVER_EXE_NAME
        if candidate.is_file():
            return candidate
    return None


def server_command() -> list[str]:
    """How to run ShopSystem: the installed exe, or launcher.py from source."""
    exe = find_server_executable()
    if exe is not None:
        return [str(exe)]
    source = app_dir().parent / "shopsystem" / "launcher.py"
    python = app_dir().parent / "shopsystem" / ".venv" / "Scripts" / "python.exe"
    if source.exists() and python.exists():
        return [str(python), str(source)]
    raise SetupError("برنامهٔ سرور (ShopSystem.exe) کنار این برنامه پیدا نشد. "
                     "نصب‌کنندهٔ «سرور فروشگاه» را دوباره اجرا کنید.")


def _server_env() -> dict:
    env = dict(os.environ)
    if not is_frozen():
        root = app_dir().parent / "shopsystem"
        env["PYTHONPATH"] = os.pathsep.join([str(root / "build_src"), str(root)])
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_server_tool(args: list[str], timeout: float = 60) -> dict:
    """Run ShopSystem with a setup flag and return its JSON answer."""
    command = server_command() + ["--data-dir", str(data_dir()), *args]
    try:
        completed = subprocess.run(command, capture_output=True, timeout=timeout,
                                   creationflags=CREATE_NO_WINDOW, env=_server_env())
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SetupError("اجرای برنامهٔ سرور ممکن نشد.", type(exc).__name__) from exc
    stdout = completed.stdout.decode("utf-8", errors="replace").strip()
    for line in reversed(stdout.splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                break
    stderr = completed.stderr.decode("utf-8", errors="replace").strip()
    # The last meaningful line is the real error (e.g. "PermissionError: ... .env").
    lines = [ln.strip() for ln in (stderr or stdout).splitlines()
             if ln.strip() and not ln.startswith("[PYI-")]
    reason = lines[-1][:300] if lines else f"کد خروج {completed.returncode}"
    raise SetupError(f"برنامهٔ سرور با خطا متوقف شد: {reason}", (stderr or stdout)[-600:])


def _run(command: list[str], *, timeout: float = 60, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, timeout=timeout,
                          creationflags=CREATE_NO_WINDOW, input=input_text, text=True,
                          encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------
# steps
# --------------------------------------------------------------------------
def harden_data_dir(extra_user: str | None = None) -> Path:
    """Create the data folder and allow only SYSTEM and Administrators (by SID,
    so it works on a Persian Windows too)."""
    folder = data_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SetupError(f"ساخت پوشهٔ داده ({folder}) ممکن نشد: {exc}", str(exc)) from exc
    grants = [f"*{SID_SYSTEM}:(OI)(CI)F", f"*{SID_ADMINISTRATORS}:(OI)(CI)F"]
    if extra_user:
        grants.append(f"{extra_user}:(OI)(CI)M")
    # Only the folder itself gets the explicit grants. Never pass /T here: applying an
    # (OI)(CI) grant to a *file* together with /inheritance:r leaves it with an empty
    # ACL, locking everybody (the service included) out of .env.
    result = _run(["icacls", str(folder), "/inheritance:r", "/grant:r", *grants, "/C", "/Q"])
    if result.returncode != 0:
        raise SetupError("دسترسی پوشهٔ دادهٔ سرور محدود نشد.", _output_tail(result))
    # Files from an earlier (partial) run: drop their own ACL so they inherit the folder's.
    # This also repairs a .env that an older setup left unreadable.
    for child in sorted(folder.rglob("*")):
        fixed = _run(["icacls", str(child), "/reset", "/C", "/Q"])
        if fixed.returncode != 0:
            raise SetupError(f"بازنشانی دسترسی «{child.name}» ممکن نشد.", _output_tail(fixed))
    _check_readable(folder / ".env")
    return folder


def _output_tail(result, limit: int = 300) -> str:
    return ((result.stderr or "") + (result.stdout or "")).strip()[-limit:]


def _check_readable(path: Path) -> None:
    """Fail with the real operating-system error if the file exists but cannot be opened."""
    if not path.exists():
        return
    try:
        with open(path, "rb"):
            pass
    except OSError as exc:
        raise SetupError(f"فایل «{path.name}» پس از تنظیم دسترسی قابل خواندن نیست: {exc}",
                         str(exc)) from exc


@dataclass
class DatabaseConfig:
    server: str
    database: str
    trusted: bool
    user: str = ""
    password: str = ""
    driver: str = "ODBC Driver 17 for SQL Server"


def write_config(db: DatabaseConfig, *, port: int, extra: dict | None = None) -> dict:
    """``ShopSystem --init-config`` with a short-lived JSON inside the locked folder.

    v2.8.1 (settings mode): an empty SQL password keeps the saved one, and an
    ``extra`` value of ``None`` (an untouched secret) keeps the saved value; an
    empty string clears that setting.
    """
    folder = data_dir()
    payload = {
        "db_server": db.server, "db_name": db.database, "db_trusted": db.trusted,
        "db_user": "" if db.trusted else db.user,
        "db_driver": db.driver, "api_port": int(port), "api_host": "0.0.0.0",
    }
    if db.trusted:
        payload["db_password"] = ""
    elif db.password:
        payload["db_password"] = db.password
    payload.update({k: v for k, v in (extra or {}).items() if v is not None})
    handle, name = tempfile.mkstemp(prefix="setup-", suffix=".json", dir=folder)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False)
        answer = run_server_tool(["--init-config", name])
    finally:
        Path(name).unlink(missing_ok=True)  # holds the DB password: never leave it behind
    if not answer.get("ok"):
        reason = answer.get("message") or answer.get("error") or str(answer)
        raise SetupError(f"نوشتن تنظیمات سرور ممکن نشد: {reason}"[:400], str(answer)[:300])
    return answer


def check_database() -> dict:
    answer = run_server_tool(["--check-db"], timeout=90)
    if not answer.get("ok"):
        # v2.8.1: the real reason in plain Persian (wrong name, no permission, …)
        reason = answer.get("message_fa") or (
            "اتصال به پایگاه‌دادهٔ حسابداری برقرار نشد. نام سرور، نام پایگاه‌داده و "
            "روش ورود را بررسی کنید.")
        if str(answer.get("error_code")) in ("4060", "229", "230"):
            reason += (" اگر نام درست است، کاربر SQL به این پایگاه‌داده دسترسی ندارد: "
                       "grant_shop_app.ps1 را برای همین پایگاه‌داده اجرا کنید.")
        raise SetupError(reason, answer.get("message") or answer.get("error", ""))
    return answer


def odbc_driver_installed(driver: str = "ODBC Driver 17 for SQL Server") -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            rf"SOFTWARE\ODBC\ODBCINST.INI\{driver}"):
            return True
    except OSError:
        return False


SERVICE_NAME = "ShopServer"
SERVICE_ACCOUNT = r"NT SERVICE\ShopServer"


def _service_tool(flag: str, message: str, timeout: float = 120) -> dict:
    answer = run_server_tool([flag], timeout=timeout)
    if not answer.get("ok"):
        raise SetupError(message, answer.get("message") or answer.get("error") or str(answer)[:300])
    return answer


def install_service() -> dict:
    """Register (or update) the Windows service ``ShopServer``.

    ShopSystem does the work (``--install-service``): virtual account
    ``NT SERVICE\\ShopServer``, automatic start at boot, restart on failure,
    Modify on the data folder for that account, and removal of the scheduled
    task older versions used.
    """
    return _service_tool("--install-service", "ثبت سرویس ویندوز برای سرور ممکن نشد.")


def start_service() -> None:
    _service_tool("--start-service", "روشن کردن سرویس سرور ممکن نشد.")


def stop_service() -> None:
    _service_tool("--stop-service", "متوقف کردن سرویس سرور ممکن نشد.")


def restart_service() -> None:
    """Stop (when running) and start ``ShopServer`` so new settings take effect."""
    try:
        stop_service()
    except SetupError as exc:   # not running yet: starting is enough
        log.info("stop before restart: %s", exc.detail or exc.message)
    start_service()


def remove_service() -> None:
    _service_tool("--uninstall-service", "حذف سرویس سرور ممکن نشد.")


_IP_PART = re.compile(r"^(?i:localsubnet|[0-9a-f:.]+(/\d{1,3})?|[0-9.]+-[0-9.]+)$")


def parse_allowed_ips(text: str) -> list[str]:
    """``192.168.10.0/24, 192.168.10.5`` -> parts; raises SetupError on junk."""
    parts = [p for p in re.split(r"[\s,;،]+", text or "") if p]
    for part in parts:
        if not _IP_PART.match(part):
            raise SetupError(f"«{part}» نشانی IP، بازه یا زیرشبکهٔ معتبری نیست.", part)
    return parts


def open_firewall(port: int, allowed_ips: str = "") -> str:
    """Inbound TCP on the port, private/domain profiles, from the local subnet
    (default) or only from the listed addresses. Returns the remote filter."""
    parts = parse_allowed_ips(allowed_ips)
    remote = ",".join(parts) if parts else "localsubnet"
    _run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={FIREWALL_RULE}"])
    command = ["netsh", "advfirewall", "firewall", "add", "rule", f"name={FIREWALL_RULE}",
               "dir=in", "action=allow", "protocol=TCP", f"localport={int(port)}",
               f"remoteip={remote}", "profile=private,domain"]
    try:
        exe = server_command()[0]
        if exe.lower().endswith("shopsystem.exe"):
            command.append(f"program={exe}")
    except SetupError:
        pass
    result = _run(command)
    if result.returncode != 0:
        raise SetupError("قانون دیوار آتش ویندوز ساخته نشد.", (result.stderr or result.stdout)[-300:])
    return remote


def network_is_public() -> bool:
    """A 'Public' network profile blocks the rule above; the owner must switch it."""
    result = _run(["powershell", "-NoProfile", "-Command",
                   "(Get-NetConnectionProfile | Select-Object -ExpandProperty NetworkCategory) -join ','"])
    return "Public" in (result.stdout or "")


def usable_lan_address(address: str) -> bool:
    """A real IPv4 address staff computers can reach: never loopback, APIPA
    (169.254.x.x, a network card without DHCP), unspecified, multicast or reserved."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return (ip.version == 4 and not (ip.is_loopback or ip.is_link_local or ip.is_unspecified
                                     or ip.is_multicast or ip.is_reserved))


def lan_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if usable_lan_address(address):
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses, key=lambda a: tuple(int(p) for p in a.split(".")))


def read_certificate() -> tuple[str, str]:
    from .api_client import fingerprint_of_pem

    cert = data_dir() / "tls" / "server.crt"
    if not cert.exists():
        raise SetupError("گواهی امنیتی سرور ساخته نشد. گزارش سرور را بررسی کنید.")
    pem = cert.read_text(encoding="ascii")
    return pem, fingerprint_of_pem(pem)


def wait_until_ready(port: int, timeout: float = 90) -> tuple[str, str]:
    """Wait for the certificate and an HTTPS answer; return (pem, fingerprint)."""
    from .api_client import ShopApiClient

    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            pem, fingerprint = read_certificate()
            client = ShopApiClient(f"https://127.0.0.1:{port}", server_cert_pem=pem, timeout=5)
            try:
                client.health()
                return pem, fingerprint
            finally:
                client.close()
        except Exception as exc:  # noqa: BLE001 - keep waiting
            last_error = type(exc).__name__
        time.sleep(2)
    raise SetupError("سرور در زمان مقرر بالا نیامد. گزارش سرور را در پوشهٔ داده ببینید.",
                     f"{data_dir() / 'app.log'} ({last_error})")


def service_key() -> str:
    """ADMIN_API_KEY from the locked .env — used once, here, for the bootstrap."""
    from dotenv import dotenv_values

    value = dotenv_values(data_dir() / ".env").get("ADMIN_API_KEY") or ""
    if not value:
        raise SetupError("کلید سرویس در تنظیمات سرور پیدا نشد.")
    return value


def current_windows_user() -> str:
    domain = os.environ.get("USERDOMAIN", "") or socket.gethostname()
    return f"{domain}\\{os.environ.get('USERNAME', '')}"


def _split_names(raw: str) -> list[str]:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


@dataclass
class CurrentConfig:
    """The saved server settings for the «تنظیمات سرور» wizard. Secrets are never
    read back: only whether each one is set."""
    db_server: str = ""
    db_name: str = ""
    db_trusted: bool = False
    db_user: str = ""
    db_password_set: bool = False
    port: int = DEFAULT_PORT
    allowed_ips: str = ""
    bank_text: str = ""
    admin_chats: str = ""
    shoptg_dir: str = ""
    allowed_databases: list[str] | None = None
    write_databases: list[str] | None = None
    secrets_set: dict[str, bool] | None = None


SECRET_KEYS = ("BALE_TOKEN", "TELEGRAM_BOT_TOKEN", "TG_API_ID", "TG_API_HASH")


def read_current_config() -> Optional[CurrentConfig]:
    """The saved ``.env`` (needs the administrator rights the wizard runs with);
    None when the server was never set up here."""
    from dotenv import dotenv_values

    env = data_dir() / ".env"
    if not env.exists():
        return None
    try:
        values = {k: (v or "") for k, v in dotenv_values(env).items()}
    except (OSError, ValueError) as exc:
        raise SetupError("تنظیمات فعلی سرور خوانده نشد.", type(exc).__name__) from exc

    def get(*keys: str) -> str:
        for key in keys:
            if values.get(key, "").strip():
                return values[key].strip()
        return ""

    try:
        port = int(get("API_PORT") or DEFAULT_PORT)
    except ValueError:
        port = DEFAULT_PORT
    trusted = get("DB_TRUSTED", "ACCOUNTING_TRUSTED_CONNECTION").lower() in ("1", "true", "yes", "on")
    return CurrentConfig(
        db_server=get("DB_SERVER", "ACCOUNTING_SERVER"),
        db_name=get("DB_NAME", "ACCOUNTING_DATABASE"),
        db_trusted=trusted,
        db_user=get("DB_USER", "ACCOUNTING_USERNAME"),
        db_password_set=bool(get("DB_PASSWORD", "ACCOUNTING_PASSWORD")),
        port=port,
        allowed_ips=get("FIREWALL_ALLOWED_IPS"),
        bank_text=get("BANK_ACCOUNT_TEXT"),
        admin_chats=get("ADMIN_CHAT_IDS"),
        shoptg_dir=get("SHOPTG_DIR"),
        allowed_databases=_split_names(get("ACCOUNTING_ALLOWED_DATABASES")),
        write_databases=_split_names(get("ACCOUNTING_WRITE_DATABASES")),
        secrets_set={key: bool(get(key)) for key in SECRET_KEYS},
    )


def server_installed_here() -> bool:
    """This computer is the shop server: the server program is installed next to
    this one and its data folder exists (the «تنظیمات سرور» button)."""
    try:
        return find_server_executable() is not None and data_dir().is_dir()
    except OSError:
        return False


def existing_config_port() -> Optional[int]:
    from dotenv import dotenv_values

    env = data_dir() / ".env"
    if not env.exists():
        return None
    try:
        return int(dotenv_values(env).get("API_PORT") or DEFAULT_PORT)
    except (ValueError, PermissionError):
        return None
