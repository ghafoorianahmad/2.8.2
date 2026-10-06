"""Staff account management (super admin only) and the audit log."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import deps
from ..db_own import OwnDB
from ..schemas import PasswordResetIn, StaffCreate, StaffOut, StaffUpdate
from ..security import Identity, require_permission
from ..staff import (
    P_SERVER_MANAGE,
    P_STAFF_MANAGE,
    ROLE_SUPER_ADMIN,
    hash_password,
    validate_password,
    validate_username,
)
from .auth import staff_out

router = APIRouter(prefix="/admin")

CAN_MANAGE = Depends(require_permission(P_STAFF_MANAGE))


def _get_or_404(db: OwnDB, staff_id: int) -> dict:
    row = db.get_staff(staff_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Staff account not found")
    return row


def _would_remove_last_super_admin(db: OwnDB, row: dict) -> bool:
    return (row["role"] == ROLE_SUPER_ADMIN and row["active"]
            and db.count_active_super_admins(exclude_id=row["id"]) == 0)


@router.get("/staff", response_model=list[StaffOut])
def list_staff(db: OwnDB = Depends(deps.get_db), _: Identity = CAN_MANAGE) -> list[StaffOut]:
    return [staff_out(r) for r in db.list_staff()]


@router.post("/staff", response_model=StaffOut, status_code=status.HTTP_201_CREATED)
def create_staff(payload: StaffCreate, db: OwnDB = Depends(deps.get_db),
                 who: Identity = CAN_MANAGE) -> StaffOut:
    for problem in (validate_username(payload.username), validate_password(payload.password)):
        if problem:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    if db.get_staff_by_username(payload.username) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")
    row = db.create_staff(payload.username, payload.full_name.strip(), payload.role,
                          hash_password(payload.password), payload.must_change_password)
    db.audit(who.actor, "staff_create", f"staff id={row['id']} role={row['role']}")
    return staff_out(row)


@router.patch("/staff/{staff_id}", response_model=StaffOut)
def update_staff(staff_id: int, payload: StaffUpdate, db: OwnDB = Depends(deps.get_db),
                 who: Identity = CAN_MANAGE) -> StaffOut:
    row = _get_or_404(db, staff_id)
    demoting = payload.role is not None and payload.role != ROLE_SUPER_ADMIN
    disabling = payload.active is False
    if (demoting or disabling) and _would_remove_last_super_admin(db, row):
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot remove the last super admin")
    fields: dict = {}
    if payload.full_name is not None:
        fields["full_name"] = payload.full_name.strip()
    if payload.role is not None:
        fields["role"] = payload.role
    if payload.active is not None:
        fields["active"] = int(payload.active)
    updated = db.update_staff(staff_id, **fields)
    if (payload.role is not None and payload.role != row["role"]) or disabling:
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
               _: Identity = Depends(require_permission(P_SERVER_MANAGE))) -> list[dict]:
    return db.list_audit(limit)

