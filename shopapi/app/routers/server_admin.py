"""Server control for the super admin: status, settings, log, restart."""
from __future__ import annotations

import json
import sys
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from .. import control, deps, monitor, sql_errors
from ..accounting_reader import AccountingReader
from ..config import Settings
from ..db_own import OwnDB
from ..pricelist import pdf_archive
from ..security import Identity, get_identity, require_permission
from ..staff import (
    P_HEALTH,
    P_SERVER_MANAGE,
    P_SERVER_VIEW,
    P_STATUS_CODES_EDIT,
    P_STATUS_CODES_VIEW,
)
from ..util import now_utc

router = APIRouter(prefix="/admin/server")

CAN_MANAGE = Depends(require_permission(P_SERVER_MANAGE))
#: v2.8.2: «تنظیمات سرور فروشگاه — دیدن»: status, settings and log, read only
CAN_SEE = Depends(require_permission(P_SERVER_VIEW))


class SettingsUpdate(BaseModel):
    values: dict[str, str]


@router.get("/health")
def server_health(db: OwnDB = Depends(deps.get_db),
                  _: Identity = Depends(require_permission(P_HEALTH))) -> dict:
    """v2.14.0 «سلامت سیستم»: each check now (with a Persian fix) and the journal."""
    from .. import selfheal

    snap = monitor.CURRENT.snapshot() if monitor.CURRENT else {"checks": {}, "checked_at": None}
    checks = [{"check": name, "label": selfheal.LABELS.get(name, name), "ok": item.get("ok"),
               "down": item.get("down"), "fix": selfheal.FIXES.get(name, "")}
              for name, item in (snap.get("checks") or {}).items()]
    return {"checked_at": snap.get("checked_at"), "checks": checks,
            "journal": selfheal.journal(db)}


@router.get("/status")
def server_status(
    settings: Settings = Depends(deps.get_settings),
    reader: AccountingReader = Depends(deps.get_reader),
    db: OwnDB = Depends(deps.get_db),
    _: Identity = CAN_SEE,
) -> dict:
    started = time.perf_counter()
    try:
        reader.ping()
        accounting = {"ok": True, "latency_ms": round((time.perf_counter() - started) * 1000)}
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        info = sql_errors.describe(exc)
        accounting = {"ok": False, "error": type(exc).__name__, "error_code": info.code,
                      "message_fa": info.message_fa}
    counts = {
        "customers_pending": len(db.list_users("pending")),
        "orders_awaiting_payment": len(db.list_orders("awaiting_payment")),
        "orders_receipt_uploaded": len(db.list_orders("receipt_uploaded")),
        "staff": db.count_staff(),
    }
    return {
        "version": control.VERSION,
        "python": sys.version.split()[0],
        "started_at": control.STARTED_AT.isoformat(timespec="seconds"),
        "uptime_seconds": int((now_utc() - control.STARTED_AT).total_seconds()),
        "accounting": accounting,
        "accounting_server": settings.accounting_server,
        "accounting_database": settings.accounting_database,
        "accounting_write_enabled": settings.write_allowed(),
        "database_allowlisted": settings.database_allowlisted() or settings.is_test_db(),
        "status_code_configured": settings.status_code_problem() is None,
        "test_mode": settings.is_test_db(),
        **settings.write_info(),
        "write_allowed_on_host": settings.write_allowed(),
        "tls_fingerprint": control.STATE.tls_fingerprint,
        "restart_available": control.STATE.restart_hook is not None,
        "settings_editable": control.STATE.env_file is not None,
        "components": control.provider_status(),
        "health": monitor.CURRENT.snapshot() if monitor.CURRENT else None,
        "telegram_worker": _tg_status(db),
        "proxy_pool": _pool_status(db),
        "backup": _backup_status(),
        # v2.13.0: every received price list is kept here (never deleted automatically)
        "pricelist_archive": pdf_archive.archive_info(settings),
        "counts": counts,
    }


def _backup_status() -> dict | None:
    """The last daily backup (no paths, no passphrase)."""
    raw = control.backup_status()
    if not raw:
        return None
    offsite = raw.get("offsite") if isinstance(raw.get("offsite"), dict) else {}
    verify = raw.get("verify") if isinstance(raw.get("verify"), dict) else {}
    return {
        "at": raw.get("at"),
        "ok": bool(raw.get("ok")),
        "error": raw.get("error"),
        "file": raw.get("file"),
        "size": raw.get("size"),
        "verified": bool(verify.get("ok")),
        "last_success_at": raw.get("last_success_at"),
        "offsite_configured": bool(offsite.get("configured")),
        "offsite_ok": offsite.get("ok"),
        "offsite_error": offsite.get("error"),
        # v2.13.0: the copy on the server itself, apart from the off-server one
        "local_ok": raw.get("local_ok"),
        "last_local_success_at": raw.get("last_local_success_at"),
        "offsite_network": bool(offsite.get("network")),
        "offsite_reason_fa": monitor.backup_reason_fa(raw),
    }


def _tg_status(db: OwnDB) -> dict | None:
    """The Telegram worker's last published status (no secrets inside)."""
    raw = db.get_state(monitor.TG_STATUS_KEY, "")
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(value, dict):
        return None
    keep = ("connected", "proxy", "login_required", "error", "at", "paused_until",
            # v2.9.0
            "api_preset", "price_channel", "pool_size")
    out = {key: value.get(key) for key in keep}
    for nested, fields in (("price", ("checked_at", "ref", "outcome", "at", "channel")),
                           ("collect", ("at", "found", "tested", "added", "via", "error"))):
        raw = value.get(nested)
        out[nested] = {k: raw.get(k) for k in fields} if isinstance(raw, dict) else {}
    if not out["collect"].get("at"):
        # v2.9.2: the last collection survives a restart of the reader
        try:
            stored = json.loads(db.get_state("worker:tg_collect_info", "") or "{}")
        except ValueError:
            stored = {}
        if isinstance(stored, dict) and stored.get("at"):
            out["collect"] = {k: stored.get(k) for k in
                              ("at", "found", "tested", "added", "via", "error")}
    asked = db.get_state("worker:tg_collect_request", "")
    out["collect"]["requested"] = bool(asked) and asked != db.get_state("worker:tg_collect_done", "")
    return out


def _pool_status(db: OwnDB) -> dict:
    """v2.9.0: the Telegram proxy pool in numbers (hosts and secrets stay out)."""
    from ..proxypool import ProxyPool, pool_summary

    worker = _tg_status(db) or {}
    try:
        target = int(worker.get("pool_size") or 10)
    except (TypeError, ValueError):
        target = 10
    return pool_summary(ProxyPool(db), target)


@router.get("/settings")
def get_settings(who: Identity = CAN_SEE) -> dict:
    if control.STATE.env_file is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Settings file not available")
    values = control.current_settings()
    if not who.can(P_STATUS_CODES_VIEW):
        # v2.17.0: «کدهای وضعیت» has its own tick
        values = {k: v for k, v in values.items() if k not in control.STATUS_CODE_KEYS}
    return {"settings": values}


@router.put("/settings")
def put_settings(payload: SettingsUpdate, db: OwnDB = Depends(deps.get_db),
                 who: Identity = CAN_MANAGE) -> dict:
    if control.STATE.env_file is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Settings file not available")
    if not payload.values:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nothing to change")
    if control.STATUS_CODE_KEYS & set(payload.values) and not who.can(P_STATUS_CODES_EDIT):
        # v2.17.0: «تنظیمات سرور — تغییر» alone does not open the status codes
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this account")
    problems = control.validate_settings(payload.values)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            {"message": "Invalid settings", "fields": problems})
    control.write_env_values(payload.values)
    # Key names only: values (tokens, bank text) never enter the audit log.
    db.audit(who.actor, "server_settings", f"keys={sorted(payload.values)}")
    return {"ok": True, "restart_required": True}


@router.get("/logs")
def get_logs(lines: int = Query(200, ge=10, le=2000), _: Identity = CAN_SEE) -> dict:
    if control.STATE.log_file is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Log file not available")
    return {"lines": control.tail_log(lines)}


@router.post("/restart")
def restart(db: OwnDB = Depends(deps.get_db), who: Identity = CAN_MANAGE) -> dict:
    hook = control.STATE.restart_hook
    if hook is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Restart not available")
    db.audit(who.actor, "server_restart", "")
    # Answer first; the process goes away a moment later and is brought back
    # by its supervisor with the current settings.
    threading.Timer(1.0, hook).start()
    return {"ok": True}


# ---- v2.9.1: off-server backup folder ---------------------------------------------------
class BackupFolderIn(BaseModel):
    folder: str
    #: v2.13.0: an account of the computer behind a network folder; an empty
    #: password with the saved user name = the saved password
    user: str = ""
    password: str = ""


def _can_test_backup(identity: Identity = Depends(get_identity)) -> Identity:
    """«تنظیمات سرور» on the server (service key) or a manager."""
    if identity.kind == "service" or (not identity.must_change_password
                                      and identity.can(P_SERVER_MANAGE)):
        return identity
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this account")


def _share_session(folder: str, user: str, password: str):
    """v2.13.0: the ShopSystem helper that signs the service in to a share of
    another computer (a no-op outside ShopSystem, e.g. plain uvicorn / tests)."""
    import contextlib

    try:
        import netshare
    except ImportError:
        return contextlib.nullcontext(False)
    return netshare.session(folder, user, password)


def check_backup_folder(folder: str, user: str = "", password: str = "") -> dict:
    """Write, read back and delete a small file in ``folder`` as THIS process (the
    service account NT SERVICE/ShopServer on the server: a network share must
    allow it). Never lists or touches anything else there. v2.13.0: with
    ``user`` / ``password`` (an account of the computer behind a network folder)
    the service signs in to that share first, as the nightly backup does."""
    import os
    import secrets
    from pathlib import Path

    raw = str(folder or "").strip()
    if not raw:
        return {"ok": False, "error": "empty", "message_fa": "پوشه‌ای وارد نشده است."}
    path = Path(raw)
    if not path.is_absolute():
        return {"ok": False, "error": "relative",
                "message_fa": r"مسیر کامل لازم است (مثل D:\Backups یا \\PC\Share)."}
    network = raw[:2] in ("\\\\", "//")
    probe = path / f".shopserver_test_{secrets.token_hex(4)}.tmp"
    try:
        with _share_session(raw, user, password):
            try:
                path.mkdir(parents=True, exist_ok=True)
                probe.write_bytes(b"ShopServer backup test")
                ok = probe.read_bytes() == b"ShopServer backup test"
            finally:
                try:
                    if probe.exists():
                        os.remove(probe)
                except OSError:
                    pass
    except OSError as exc:
        reason = type(exc).__name__
        message_fa = getattr(exc, "message_fa", "")
        if message_fa:
            message = message_fa
        elif isinstance(exc, PermissionError) and network and not user:
            message = ("دسترسی نیست: این پوشه روی رایانهٔ دیگری است و سرویس سرور آن‌جا نام "
                       "کاربری ندارد. نام کاربری و گذرواژهٔ همان رایانه را وارد کنید.")
        elif isinstance(exc, PermissionError):
            message = ("دسترسی نوشتن نیست؛ به این حساب روی رایانهٔ مقصد اجازهٔ نوشتن بدهید."
                       if network else "دسترسی نوشتن نیست.")
        else:
            message = "پوشه پیدا یا ساخته نشد (نشانی شبکه، روشن بودن رایانهٔ مقصد)."
        return {"ok": False, "error": reason, "message_fa": message}
    return {"ok": bool(ok), "error": None if ok else "readback",
            "message_fa": "نوشتن، خواندن و پاک کردن فایل آزمایشی با حساب سرویس سرور موفق بود."
            if ok else "فایل آزمایشی درست خوانده نشد."}


@router.post("/backup-test")
def backup_test(payload: BackupFolderIn, _: Identity = Depends(_can_test_backup)) -> dict:
    import os

    user = payload.user.strip()
    password = payload.password
    saved_user = os.environ.get("BACKUP_SHARE_USER", "").strip()
    if user and not password and user.lower() == saved_user.lower():
        password = os.environ.get("BACKUP_SHARE_PASSWORD", "")   # «خالی = بدون تغییر»
    return check_backup_folder(payload.folder, user, password)


# ---- v2.9.4: «تنظیمات سرور» on the server itself ----------------------------------------
def _service_only(identity: Identity = Depends(get_identity)) -> Identity:
    """Only the server's own key (the setup on the server computer, loopback)."""
    if identity.kind != "service":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this account")
    return identity


class DbCheckIn(BaseModel):
    server: str
    database: str


@router.post("/db-check")
def db_check(payload: DbCheckIn, settings: Settings = Depends(deps.get_settings),
             _: Identity = Depends(_service_only)) -> dict:
    """«آزمایش اتصال» by the RUNNING SERVICE (its own Windows account) for the
    server / database chosen in the setup, with Windows sign-in. Read only."""
    from dataclasses import replace

    trial = replace(settings, accounting_server=payload.server.strip(),
                    accounting_database=payload.database.strip(), accounting_trusted=True)
    try:
        reader = AccountingReader(trial)
        reader.ping()
        return {"ok": True, "groups": len(reader.list_groups())}
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        info = sql_errors.describe(exc)
        return {"ok": False, "error_code": info.code, "message_fa": info.message_fa}


@router.get("/order-status-codes")
def order_status_codes(reader: AccountingReader = Depends(deps.get_reader),
                       identity: Identity = Depends(get_identity)) -> dict:
    """«راهنمای کد وضعیت سفارش»: Status values and counts of the accounting order
    table and the latest orders «سازه حساب» made itself. Read only."""
    if not (identity.kind == "service" or (not identity.must_change_password
                                           and identity.can(P_STATUS_CODES_VIEW))):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this account")
    try:
        return {"ok": True, **reader.order_status_overview()}
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        info = sql_errors.describe(exc)
        return {"ok": False, "error_code": info.code, "message_fa": info.message_fa}


class CleanupIn(BaseModel):
    confirm: str


def _cleanup_paths(settings: Settings):
    from pathlib import Path

    bots = control.STATE.env_file.parent / "shopbots.db" if control.STATE.env_file else None
    receipts = settings.receipts_path()
    return (Path(bots) if bots else None), receipts


@router.get("/cleanup-test-data")
def cleanup_preview(settings: Settings = Depends(deps.get_settings),
                    db: OwnDB = Depends(deps.get_db),
                    _: Identity = Depends(_service_only)) -> dict:
    from .. import cleanup

    bots, receipts = _cleanup_paths(settings)
    return {**cleanup.preview(db, bots_path=bots, receipts_dir=receipts),
            "backup_fresh": cleanup.backup_is_fresh(control.backup_status() or {}),
            "confirm_text": cleanup.CONFIRM_TEXT}


@router.post("/cleanup-test-data")
def cleanup_run(payload: CleanupIn, settings: Settings = Depends(deps.get_settings),
                db: OwnDB = Depends(deps.get_db),
                _: Identity = Depends(_service_only)) -> dict:
    """«پاک‌سازی داده‌های آزمایشی»: only the shop's own SQLite data (never the
    accounting database), after a fresh verified backup and the typed confirmation."""
    from .. import cleanup

    bots, receipts = _cleanup_paths(settings)
    try:
        return cleanup.clear_test_data(db, bots_path=bots, receipts_dir=receipts,
                                       confirm=payload.confirm,
                                       backup_status=control.backup_status() or {})
    except cleanup.CleanupError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
