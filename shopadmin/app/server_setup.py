"""Server setup on the server computer itself (run as administrator).

What it does, in order — each step is a small function so the wizard can show
progress and stop on the first problem:

1. lock the data folder (%ProgramData%\\ShopServer) to SYSTEM + Administrators,
2. write ``.env`` through ``ShopSystem.exe --init-config`` (random API keys;
   the database password travels in a JSON file inside the locked folder,
   never on a command line, and the file is deleted right away),
3. test the accounting connection with ``ShopSystem.exe --check-db``,
4. register the Windows scheduled task that starts the server at boot and
   restarts it on failure, plus a firewall rule for the local network only,
5. start it, wait for HTTPS, pin its certificate (read from the local file —
   no trust-on-first-use needed on the server itself),
6. create the first super admin with the server-local service key.

Nothing here is reachable from the network; it needs a local administrator.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

from .logging_setup import get_logger
from .paths import app_dir, is_frozen

log = get_logger("server_setup")

TASK_NAME = "ShopServer"
FIREWALL_RULE = "ShopServer"
DEFAULT_PORT = 8443
SID_SYSTEM = "S-1-5-18"
SID_ADMINISTRATORS = "S-1-5-32-544"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class SetupError(Exception):
    """A setup step failed; ``message`` is Persian and safe to show."""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


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
def server_command() -> list[str]:
    """How to run ShopSystem: the installed exe, or launcher.py from source."""
    from .services.child_process import find_service_executable

    exe = find_service_executable()
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
    output = completed.stdout.decode("utf-8", errors="replace").strip().splitlines()
    for line in reversed(output):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                break
    raise SetupError("پاسخ برنامهٔ سرور قابل خواندن نبود.",
                     completed.stderr.decode("utf-8", errors="replace")[-300:])


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
    folder.mkdir(parents=True, exist_ok=True)
    grants = [f"*{SID_SYSTEM}:(OI)(CI)F", f"*{SID_ADMINISTRATORS}:(OI)(CI)F"]
    if extra_user:
        grants.append(f"{extra_user}:(OI)(CI)M")
    result = _run(["icacls", str(folder), "/inheritance:r", "/grant:r", *grants, "/T", "/C", "/Q"])
    if result.returncode != 0:
        raise SetupError("دسترسی پوشهٔ دادهٔ سرور محدود نشد.", result.stderr[-300:])
    return folder


@dataclass
class DatabaseConfig:
    server: str
    database: str
    trusted: bool
    user: str = ""
    password: str = ""
    driver: str = "ODBC Driver 17 for SQL Server"


def write_config(db: DatabaseConfig, *, port: int, extra: dict | None = None) -> dict:
    """``ShopSystem --init-config`` with a short-lived JSON inside the locked folder."""
    folder = data_dir()
    payload = {
        "db_server": db.server, "db_name": db.database, "db_trusted": db.trusted,
        "db_user": "" if db.trusted else db.user,
        "db_password": "" if db.trusted else db.password,
        "db_driver": db.driver, "api_port": int(port), "api_host": "0.0.0.0",
    }
    payload.update({k: v for k, v in (extra or {}).items() if v not in (None, "")})
    handle, name = tempfile.mkstemp(prefix="setup-", suffix=".json", dir=folder)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False)
    answer = run_server_tool(["--init-config", name])
    Path(name).unlink(missing_ok=True)
    if not answer.get("ok"):
        raise SetupError("نوشتن تنظیمات سرور ممکن نشد.", str(answer)[:300])
    return answer


def check_database() -> dict:
    answer = run_server_tool(["--check-db"], timeout=90)
    if not answer.get("ok"):
        raise SetupError(
            "اتصال به پایگاه‌دادهٔ حسابداری برقرار نشد. نام سرور، نام پایگاه‌داده و "
            "روش ورود را بررسی کنید.", answer.get("message") or answer.get("error", ""))
    return answer


def odbc_driver_installed(driver: str = "ODBC Driver 17 for SQL Server") -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            rf"SOFTWARE\ODBC\ODBCINST.INI\{driver}"):
            return True
    except OSError:
        return False


def task_xml(command: list[str], *, run_as_user: str | None) -> str:
    exe, args = command[0], command[1:] + ["--service", "--data-dir", str(data_dir())]
    if run_as_user:
        principal = (f"<UserId>{escape(run_as_user)}</UserId><LogonType>Password</LogonType>"
                     "<RunLevel>HighestAvailable</RunLevel>")
    else:
        principal = f"<UserId>{SID_SYSTEM}</UserId><RunLevel>HighestAvailable</RunLevel>"
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Shop server: API and Bale/Telegram bots</Description></RegistrationInfo>
  <Triggers><BootTrigger><Enabled>true</Enabled><Delay>PT30S</Delay></BootTrigger></Triggers>
  <Principals><Principal id="Author">{principal}</Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>5</Priority>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(exe)}</Command>
      <Arguments>{escape(subprocess.list2cmdline(args))}</Arguments>
      <WorkingDirectory>{escape(str(Path(exe).parent))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def register_task(*, run_as_user: str | None = None, password: str = "") -> None:
    """Create (or replace) the boot-time scheduled task."""
    stop_task()
    xml_path = data_dir() / "task.xml"
    xml_path.write_text(task_xml(server_command(), run_as_user=run_as_user), encoding="utf-16")
    command = ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(xml_path), "/F"]
    if run_as_user:
        command += ["/RU", run_as_user, "/RP", password]
    try:
        result = _run(command)
    finally:
        xml_path.unlink(missing_ok=True)
    if result.returncode != 0:
        raise SetupError("ساخت وظیفهٔ خودکار ویندوز برای سرور ممکن نشد. اگر حساب ویندوز "
                         "را انتخاب کرده‌اید، گذرواژهٔ آن را بررسی کنید.",
                         (result.stderr or result.stdout)[-300:])


def stop_task() -> None:
    _run(["schtasks", "/End", "/TN", TASK_NAME])


def start_task() -> None:
    result = _run(["schtasks", "/Run", "/TN", TASK_NAME])
    if result.returncode != 0:
        raise SetupError("روشن کردن سرور ممکن نشد.", (result.stderr or result.stdout)[-300:])


def remove_task() -> None:
    stop_task()
    _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])


def open_firewall(port: int) -> None:
    """Inbound TCP on the port, from the local network only, private/domain profiles."""
    _run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={FIREWALL_RULE}"])
    command = ["netsh", "advfirewall", "firewall", "add", "rule", f"name={FIREWALL_RULE}",
               "dir=in", "action=allow", "protocol=TCP", f"localport={int(port)}",
               "remoteip=localsubnet", "profile=private,domain"]
    try:
        exe = server_command()[0]
        if exe.lower().endswith("shopsystem.exe"):
            command.append(f"program={exe}")
    except SetupError:
        pass
    result = _run(command)
    if result.returncode != 0:
        raise SetupError("قانون دیوار آتش ویندوز ساخته نشد.", (result.stderr or result.stdout)[-300:])


def network_is_public() -> bool:
    """A 'Public' network profile blocks the rule above; the owner must switch it."""
    result = _run(["powershell", "-NoProfile", "-Command",
                   "(Get-NetConnectionProfile | Select-Object -ExpandProperty NetworkCategory) -join ','"])
    return "Public" in (result.stdout or "")


def lan_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses)


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


def existing_config_port() -> Optional[int]:
    from dotenv import dotenv_values

    env = data_dir() / ".env"
    if not env.exists():
        return None
    try:
        return int(dotenv_values(env).get("API_PORT") or DEFAULT_PORT)
    except (ValueError, PermissionError):
        return None
