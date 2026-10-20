"""Staff account management (super admin only) and the audit log."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import deps
from ..db_own import OwnDB
from ..schemas import PasswordRequestOut, PasswordResetIn, StaffCreate, StaffOut, StaffUpdate
from ..security import Identity, require_permission
from ..staff import (
    ALL_PERMISSIONS,
    DEFAULT_RESET_PASSWORD,
    LEGACY_ROLE_MAP,
    PERMISSION_LABELS,
    P_PASSWORD_REQUESTS,
    P_PASSWORDS_VIEW,
    P_SERVER_VIEW,
    P_STAFF_MANAGE,
    P_STAFF_VIEW,
    ROLE_SUPER_ADMIN,
    hash_password,
    validate_password,
    sections_out,
    validate_username,
)
from ..util import now_utc
from .auth import FORGOT_APPROVED_MINUTES, staff_out

router = APIRouter(prefix="/admin")

CAN_MANAGE = Depends(require_permission(P_STAFF_MANAGE))
CAN_SEE_STAFF = Depends(require_permission(P_STAFF_VIEW))


def _get_or_404(db: OwnDB, staff_id: int) -> dict:
    row = db.get_staff(staff_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Staff account not found")
    return row


def _would_remove_last_super_admin(db: OwnDB, row: dict) -> bool:
    return (row["role"] == ROLE_SUPER_ADMIN and row["active"]
            and db.count_active_super_admins(exclude_id=row["id"]) == 0)


def _role(value: str) -> str:
    """v2.7.0: «مدیر» or «کاربر فروش»; the old codes are mapped."""
    return LEGACY_ROLE_MAP.get(value, value)


def _ticks(values) -> str:
    unknown = [v for v in values or () if v not in ALL_PERMISSIONS]
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown permission")
    return ",".join(sorted(set(values or ())))


@router.get("/permissions")
def list_permissions(_: Identity = CAN_SEE_STAFF) -> list[dict]:
    """Every permission with its Persian name (the per-user ticks in ShopAdmin)."""
    return [{"name": name, "label": label} for name, label in PERMISSION_LABELS.items()]


@router.get("/permission-sections")
def list_permission_sections(_: Identity = CAN_SEE_STAFF) -> list[dict]:
    """v2.8.2: the permission table: one row per section, «دیدن» / «تغییر»."""
    return sections_out()


@router.get("/staff", response_model=list[StaffOut])
def list_staff(db: OwnDB = Depends(deps.get_db), _: Identity = CAN_SEE_STAFF) -> list[StaffOut]:
    return [staff_out(r) for r in db.list_staff()]


@router.post("/staff", response_model=StaffOut, status_code=status.HTTP_201_CREATED)
def create_staff(payload: StaffCreate, db: OwnDB = Depends(deps.get_db),
                 who: Identity = CAN_MANAGE) -> StaffOut:
    for problem in (validate_username(payload.username), validate_password(payload.password)):
        if problem:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    if db.get_staff_by_username(payload.username) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")
    grants, revokes = _ticks(payload.extra_permissions), _ticks(payload.removed_permissions)
    row = db.create_staff(payload.username, payload.full_name.strip(), _role(payload.role),
                          hash_password(payload.password), payload.must_change_password)
    if grants or revokes:
        row = db.update_staff(row["id"], perm_grant=grants, perm_revoke=revokes)
    db.audit(who.actor, "staff_create", f"staff id={row['id']} role={row['role']}")
    return staff_out(row)


@router.patch("/staff/{staff_id}", response_model=StaffOut)
def update_staff(staff_id: int, payload: StaffUpdate, db: OwnDB = Depends(deps.get_db),
                 who: Identity = CAN_MANAGE) -> StaffOut:
    row = _get_or_404(db, staff_id)
    role = _role(payload.role) if payload.role is not None else None
    demoting = role is not None and role != ROLE_SUPER_ADMIN
    disabling = payload.active is False
    if (demoting or disabling) and _would_remove_last_super_admin(db, row):
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot remove the last super admin")
    fields: dict = {}
    if payload.full_name is not None:
        fields["full_name"] = payload.full_name.strip()
    if role is not None:
        fields["role"] = role
    if payload.active is not None:
        fields["active"] = int(payload.active)
    if payload.extra_permissions is not None:
        fields["perm_grant"] = _ticks(payload.extra_permissions)
    if payload.removed_permissions is not None:
        fields["perm_revoke"] = _ticks(payload.removed_permissions)
    ticks_changed = any(k in fields and fields[k] != (row.get(k) or "")
                        for k in ("perm_grant", "perm_revoke"))
    updated = db.update_staff(staff_id, **fields)
    if (role is not None and role != row["role"]) or disabling or ticks_changed:
        # New rights take effect immediately: existing sessions are dropped.
        db.delete_sessions_for_user(staff_id)
    db.audit(who.actor, "staff_update", f"staff id={staff_id} fields={sorted(fields)}")
    return staff_out(updated)


@router.post("/staff/{staff_id}/password", response_model=StaffOut)
def reset_password(staff_id: int, payload: PasswordResetIn, db: OwnDB = Depends(deps.get_db),
                   who: Identity = CAN_MANAGE) -> StaffOut:
    _get_or_404(db, staff_id)
    problem = validate_password(payload.password)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    updated = db.update_staff(staff_id, password_hash=hash_password(payload.password),
                              must_change_password=int(payload.must_change_password),
                              failed_attempts=0, locked_until=None)
    db.delete_sessions_for_user(staff_id)
    db.audit(who.actor, "staff_password_reset", f"staff id={staff_id}")
    return staff_out(updated)


@router.post("/staff/{staff_id}/reset-default", response_model=StaffOut)
def reset_to_default_password(staff_id: int, db: OwnDB = Depends(deps.get_db),
                              who: Identity = CAN_MANAGE) -> StaffOut:
    """Reset to the well-known temporary password; the account must change it
    at its next login (until then it can do nothing else)."""
    _get_or_404(db, staff_id)
    updated = db.update_staff(staff_id, password_hash=hash_password(DEFAULT_RESET_PASSWORD),
                              must_change_password=1, failed_attempts=0, locked_until=None)
    db.delete_sessions_for_user(staff_id)
    db.audit(who.actor, "staff_password_reset_default", f"staff id={staff_id}")
    return staff_out(updated)


@router.post("/staff/{staff_id}/unlock", response_model=StaffOut)
def unlock_staff(staff_id: int, db: OwnDB = Depends(deps.get_db),
                 who: Identity = CAN_MANAGE) -> StaffOut:
    _get_or_404(db, staff_id)
    updated = db.update_staff(staff_id, failed_attempts=0, locked_until=None)
    db.audit(who.actor, "staff_unlock", f"staff id={staff_id}")
    return staff_out(updated)


@router.delete("/staff/{staff_id}")
def delete_staff(staff_id: int, db: OwnDB = Depends(deps.get_db),
                 who: Identity = CAN_MANAGE) -> dict:
    row = _get_or_404(db, staff_id)
    if who.user_id == staff_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot delete your own account")
    if _would_remove_last_super_admin(db, row):
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot remove the last super admin")
    db.delete_staff(staff_id)
    db.audit(who.actor, "staff_delete", f"staff id={staff_id} username={row['username']}")
    return {"ok": True}


@router.get("/audit")
def list_audit(limit: int = Query(200, ge=1, le=1000), db: OwnDB = Depends(deps.get_db),
               _: Identity = Depends(require_permission(P_SERVER_VIEW))) -> list[dict]:
    return db.list_audit(limit)



# ---- forgot-password requests (admins) ---------------------------------------
CAN_DECIDE_PASSWORDS = Depends(require_permission(P_PASSWORD_REQUESTS))
CAN_SEE_PASSWORDS = Depends(require_permission(P_PASSWORDS_VIEW))


def _decidable(db: OwnDB, request_id: int, who: Identity) -> dict:
    row = db.get_password_request(request_id)
    if row is None or row["status"] != "pending":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such pending request")
    if row["role"] == ROLE_SUPER_ADMIN and who.role != ROLE_SUPER_ADMIN:
        # An admin must not be able to take over a super admin's account.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a super admin may decide this")
    return row


@router.get("/password-requests", response_model=list[PasswordRequestOut])
def list_password_requests(db: OwnDB = Depends(deps.get_db),
                           who: Identity = CAN_SEE_PASSWORDS) -> list[PasswordRequestOut]:
    rows = db.list_pending_password_requests()
    if who.role != ROLE_SUPER_ADMIN:
        rows = [r for r in rows if r["role"] != ROLE_SUPER_ADMIN]
    return [PasswordRequestOut(**r) for r in rows]


@router.post("/password-requests/{request_id}/approve")
def approve_password_request(request_id: int, db: OwnDB = Depends(deps.get_db),
                             who: Identity = CAN_DECIDE_PASSWORDS) -> dict:
    row = _decidable(db, request_id, who)
    expires = (now_utc() + timedelta(minutes=FORGOT_APPROVED_MINUTES)).isoformat(
        timespec="seconds")
    db.set_password_request_status(request_id, "approved", who.actor, expires_at=expires)
    db.audit(who.actor, "password_request_approved", f"staff id={row['staff_id']}")
    return {"ok": True}


@router.post("/password-requests/{request_id}/reject")
def reject_password_request(request_id: int, db: OwnDB = Depends(deps.get_db),
                            who: Identity = CAN_DECIDE_PASSWORDS) -> dict:
    row = _decidable(db, request_id, who)
    db.set_password_request_status(request_id, "rejected", who.actor)
    db.audit(who.actor, "password_request_rejected", f"staff id={row['staff_id']}")
    return {"ok": True}
