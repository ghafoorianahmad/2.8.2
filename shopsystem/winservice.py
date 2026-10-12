"""The shop server as a real Windows service (REQUIREMENTS §1).

* Service ``ShopServer`` runs ``ShopSystem.exe --winservice --data-dir <folder>``
  (the supervisor) at boot, without anybody logging in.
* Account: the virtual service account ``NT SERVICE\\ShopServer`` - dedicated,
  not an administrator, no password to store or expire.
* The service control manager restarts it when it fails; the supervisor inside
  restarts each child process (API + Bale bot, Telegram worker) on its own.
* The account gets Modify on the data folder (``.env`` is edited remotely by
  super admins, SQLite, receipts, logs) and read on the Telegram worker's
  ``.env`` / session, nothing else.

Install, remove and query run ``sc.exe`` / ``icacls`` / ``schtasks`` through an
injectable runner, so the exact commands are unit-tested without touching the
system. Hosting (``run_service``) uses pywin32.
"""
from __future__ import annotations

import re
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional, Sequence

SERVICE_NAME = "ShopServer"
DISPLAY_NAME = "Shop Server (API + Bale bot)"
DESCRIPTION = ("Asre Ertebatat 2 shop server: shopapi, the Bale bot and the Telegram "
               "price/proxy worker. Managed by ShopAdmin.")
SERVICE_ACCOUNT = rf"NT SERVICE\{SERVICE_NAME}"
#: The scheduled task used before Phase 4; removed when the service is installed.
LEGACY_TASK = "ShopServer"
#: Restart after 10 s, 30 s, then every 60 s; the failure count resets after a day.
FAILURE_ACTIONS = "restart/10000/restart/30000/restart/60000"

STATES = {1: "stopped", 2: "start_pending", 3: "stop_pending", 4: "running",
          5: "continue_pending", 6: "pause_pending", 7: "paused"}

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


class ServiceError(RuntimeError):
    pass


def _default_runner(command: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(command), capture_output=True, text=True, errors="replace",
                          timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _tail(result: subprocess.CompletedProcess, limit: int = 300) -> str:
    return ((result.stdout or "") + (result.stderr or "")).strip()[-limit:]


def service_command(exe_command: Sequence[str], data_dir: Path) -> str:
    """The ``binPath`` the service control manager starts."""
    return subprocess.list2cmdline([*exe_command, "--winservice", "--data-dir", str(data_dir)])


def install_commands(bin_path: str, *, exists: bool) -> list[list[str]]:
    verb = "config" if exists else "create"
    return [
        ["sc.exe", verb, SERVICE_NAME, "binPath=", bin_path, "start=", "auto",
         "obj=", SERVICE_ACCOUNT, "DisplayName=", DISPLAY_NAME],
        ["sc.exe", "description", SERVICE_NAME, DESCRIPTION],
        ["sc.exe", "failure", SERVICE_NAME, "reset=", "86400", "actions=", FAILURE_ACTIONS],
        # also restart when the supervisor stops with an error code (not only crashes)
        ["sc.exe", "failureflag", SERVICE_NAME, "1"],
        # a virtual account needs the service SID
        ["sc.exe", "sidtype", SERVICE_NAME, "unrestricted"],
    ]


def local_backup_dir(raw: Optional[str]) -> Optional[Path]:
    """``BACKUP_COPY_DIR`` when it is a folder on a local disk the service account
    can be granted (a share is granted on the file server; a drive root never)."""
    text = (raw or "").strip()
    if not text or text.startswith("\\\\") or text.startswith("//"):
        return None
    path = Path(text)
    if not path.is_absolute() or path == Path(path.anchor):
        return None
    return path


def acl_commands(data_dir: Path, *, shoptg_dir: Optional[Path] = None,
                 shoptg_data: Optional[Path] = None,
                 backup_dir: Optional[Path] = None) -> list[list[str]]:
    """Grants for the service account (added, never replacing other entries)."""
    commands = [["icacls", str(data_dir), "/grant", f"{SERVICE_ACCOUNT}:(OI)(CI)M", "/C", "/Q"]]
    if backup_dir is not None:
        # the off-server copy (encrypted): a USB / second disk folder
        commands.append(["icacls", str(backup_dir), "/grant",
                         f"{SERVICE_ACCOUNT}:(OI)(CI)M", "/C", "/Q"])
    # Files written before the service existed may carry their own (protected) ACL.
    for path in _protected_files(data_dir):
        commands.append(["icacls", str(path), "/grant", f"{SERVICE_ACCOUNT}:M", "/C", "/Q"])
    if shoptg_dir is not None and (shoptg_dir / ".env").exists():
        commands.append(["icacls", str(shoptg_dir / ".env"), "/grant",
                         f"{SERVICE_ACCOUNT}:R", "/C", "/Q"])
    if shoptg_data is not None and shoptg_data.exists():
        # inheritance is removed there (session file): grant the folder and each file
        commands.append(["icacls", str(shoptg_data), "/grant",
                         f"{SERVICE_ACCOUNT}:(OI)(CI)M", "/C", "/Q"])
        for path in sorted(p for p in shoptg_data.iterdir() if p.is_file()):
            commands.append(["icacls", str(path), "/grant", f"{SERVICE_ACCOUNT}:M", "/C", "/Q"])
    return commands


def _protected_files(data_dir: Path) -> list[Path]:
    names = (".env", "shopapi.db", "shopbots.db", "messages.fa.json")
    out = [data_dir / name for name in names if (data_dir / name).exists()]
    tls = data_dir / "tls"
    if tls.exists():
        out += sorted(p for p in tls.iterdir() if p.is_file())
    return out


def exists(run: Runner | None = None) -> bool:
    run = run or _default_runner
    return run(["sc.exe", "query", SERVICE_NAME]).returncode == 0


_STATE_RE = re.compile(r":\s*([1-7])\s+[A-Z_]+")


def state(run: Runner | None = None) -> Optional[str]:
    """``running`` / ``stopped`` / ... or ``None`` when the service is not installed."""
    run = run or _default_runner
    result = run(["sc.exe", "query", SERVICE_NAME])
    if result.returncode != 0:
        return None
    match = _STATE_RE.search(result.stdout or "")
    return STATES.get(int(match.group(1)), "unknown") if match else "unknown"


def install(exe_command: Sequence[str], data_dir: Path, *, shoptg_dir: Optional[Path] = None,
            shoptg_data: Optional[Path] = None, backup_dir: Optional[Path] = None,
            run: Runner | None = None) -> dict:
    """Create or update the service, grant its account, drop the old boot task."""
    run = run or _default_runner
    already = exists(run)
    if already:
        stop(run)
    for command in install_commands(service_command(exe_command, data_dir), exists=already):
        result = run(command)
        if result.returncode != 0:
            raise ServiceError(f"{' '.join(command[:2])} failed: {_tail(result)}")
    if backup_dir is not None:
        backup_dir.mkdir(parents=True, exist_ok=True)
    for command in acl_commands(data_dir, shoptg_dir=shoptg_dir, shoptg_data=shoptg_data,
                                backup_dir=backup_dir):
        result = run(command)
        if result.returncode != 0:
            raise ServiceError(f"icacls failed for {command[1]}: {_tail(result)}")
    legacy = run(["schtasks", "/Query", "/TN", LEGACY_TASK]).returncode == 0
    if legacy:
        run(["schtasks", "/End", "/TN", LEGACY_TASK])
        run(["schtasks", "/Delete", "/TN", LEGACY_TASK, "/F"])
    return {"ok": True, "service": SERVICE_NAME, "account": SERVICE_ACCOUNT,
            "updated": already, "legacy_task_removed": legacy}


def start(run: Runner | None = None) -> None:
    run = run or _default_runner
    if state(run) == "running":
        return
    result = run(["sc.exe", "start", SERVICE_NAME])
    if result.returncode != 0 and state(run) not in ("running", "start_pending"):
        raise ServiceError(f"sc start failed: {_tail(result)}")


def stop(run: Runner | None = None, *, timeout: float = 60,
         sleep: Callable[[float], None] | None = None) -> None:
    run = run or _default_runner
    import time

    sleep = sleep or time.sleep
    if state(run) in (None, "stopped"):
        return
    run(["sc.exe", "stop", SERVICE_NAME])
    waited = 0.0
    while waited < timeout:
        if state(run) in (None, "stopped"):
            return
        sleep(1.0)
        waited += 1.0
    raise ServiceError("the service did not stop in time")


def uninstall(data_dir: Path, *, shoptg_dir: Optional[Path] = None,
              shoptg_data: Optional[Path] = None, backup_dir: Optional[Path] = None,
              run: Runner | None = None) -> dict:
    """Stop and delete the service; take its grants away. Data stays."""
    run = run or _default_runner
    if not exists(run):
        return {"ok": True, "removed": False}
    stop(run)
    targets = [data_dir]
    if shoptg_dir is not None:
        targets.append(shoptg_dir / ".env")
    if shoptg_data is not None:
        targets.append(shoptg_data)
    if backup_dir is not None:
        targets.append(backup_dir)
    for target in targets:
        if Path(target).exists():
            # /T: also the per-file grants added by install()
            run(["icacls", str(target), "/remove:g", SERVICE_ACCOUNT, "/T", "/C", "/Q"])
    result = run(["sc.exe", "delete", SERVICE_NAME])
    if result.returncode != 0:
        raise ServiceError(f"sc delete failed: {_tail(result)}")
    return {"ok": True, "removed": True}


# --------------------------------------------------------------------------
# hosting (called when the service control manager starts the exe)
# --------------------------------------------------------------------------
def run_service(main: Callable[[threading.Event], int]) -> int:
    """Hand the process to the service control manager; ``main(stop_event)``
    runs until the service is stopped."""
    import servicemanager
    import win32service
    import win32serviceutil

    class ShopServerService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = DISPLAY_NAME

        def __init__(self, args):
            super().__init__(args)
            self.stop_event = threading.Event()

        def SvcStop(self):  # noqa: N802 - pywin32 API
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            self.stop_event.set()

        def SvcDoRun(self):  # noqa: N802 - pywin32 API
            main(self.stop_event)

    servicemanager.Initialize()
    servicemanager.PrepareToHostSingle(ShopServerService)
    servicemanager.StartServiceCtrlDispatcher()
    return 0
