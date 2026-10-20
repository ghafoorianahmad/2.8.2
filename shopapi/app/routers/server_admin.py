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
from ..security import Identity, require_permission
from ..staff import P_SERVER_MANAGE
from ..util import now_utc

router = APIRouter(prefix="/admin/server")

CAN_MANAGE = Depends(require_permission(P_SERVER_MANAGE))


class SettingsUpdate(BaseModel):
    values: dict[str, str]


@router.get("/status")
def server_status(
    settings: Settings = Depends(deps.get_settings),
    reader: AccountingReader = Depends(deps.get_reader),
    db: OwnDB = Depends(deps.get_db),
    _: Identity = CAN_MANAGE,
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
        "backup": _backup_status(),
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
    keep = ("connected", "proxy", "login_required", "error", "at")
    return {key: value.get(key) for key in keep}


@router.get("/settings")
def get_settings(_: Identity = CAN_MANAGE) -> dict:
    if control.STATE.env_file is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Settings file not available")
    return {"settings": control.current_settings()}


@router.put("/settings")
def put_settings(payload: SettingsUpdate, db: OwnDB = Depends(deps.get_db),
                 who: Identity = CAN_MANAGE) -> dict:
    if control.STATE.env_file is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Settings file not available")
    if not payload.values:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nothing to change")
    problems = control.validate_settings(payload.values)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            {"message": "Invalid settings", "fields": problems})
    control.write_env_values(payload.values)
    # Key names only: values (tokens, bank text) never enter the audit log.
    db.audit(who.actor, "server_settings", f"keys={sorted(payload.values)}")
    return {"ok": True, "restart_required": True}


@router.get("/logs")
def get_logs(lines: int = Query(200, ge=10, le=2000), _: Identity = CAN_MANAGE) -> dict:
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
