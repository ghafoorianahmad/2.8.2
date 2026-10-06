"""Tests for authentication, password hashing and role permissions."""
from __future__ import annotations

import pytest

from app.auth import (
    LOCK_MINUTES,
    MAX_FAILED_ATTEMPTS,
    MSG_CANNOT_DELETE_SELF,
    MSG_CANNOT_DEACTIVATE_SELF,
    MSG_INVALID_CREDENTIALS,
    MSG_LAST_SUPER_ADMIN,
    MSG_PASSWORD_MISMATCH,
    MSG_USERNAME_TAKEN,
    MSG_USERNAME_INVALID,
    MSG_USER_DISABLED,
    MSG_USER_LOCKED,
    MSG_WRONG_CURRENT_PASSWORD,
    AuthError,
    AuthService,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.permissions import (
    ORDERS_APPROVE_PAYMENT,
    SETTINGS_EDIT_CONNECTION,
    USERS_MANAGE,
    has_permission,
    role_permissions,
)
from app.statuses import ROLE_ADMIN, ROLE_OPERATOR, ROLE_SUPER_ADMIN, ROLE_VIEWER


# ---- password hashing -----------------------------------------------------
def test_hash_is_bcrypt_and_not_reversible():
    digest = hash_password("Secret123")
    assert digest.startswith("$2")
    assert "Secret123" not in digest


def test_same_password_gives_different_hashes():
    assert hash_password("Secret123") != hash_password("Secret123")


def test_verify_password_accepts_correct_and_rejects_wrong():
    digest = hash_password("Secret123")
    assert verify_password("Secret123", digest) is True
    assert verify_password("secret123", digest) is False
    assert verify_password("", digest) is False


def test_verify_password_tolerates_a_corrupt_hash():
    assert verify_password("x", "") is False
    assert verify_password("x", "not-a-hash") is False


def test_validate_password_strength():
    assert validate_password_strength("12345") is not None
    assert validate_password_strength("123456") is None


# ---- first-run bootstrap --------------------------------------------------
def test_first_super_admin_is_created_once(auth):
    assert auth.needs_first_super_admin is True
    principal = auth.create_first_super_admin("owner", "مالک فروشگاه", "Secret123")
    assert principal.role == ROLE_SUPER_ADMIN
    assert principal.full_name == "مالک فروشگاه"
    assert auth.needs_first_super_admin is False
    with pytest.raises(AuthError):
        auth.create_first_super_admin("owner2", "دوم", "Secret123")


def test_created_password_is_never_stored_in_plain_text(store, auth):
    auth.create_first_super_admin("owner", "مالک", "Secret123")
    row = store.get_admin_user_by_username("owner")
    assert "Secret123" not in row["password_hash"]
    assert verify_password("Secret123", row["password_hash"])


# ---- login ----------------------------------------------------------------
def test_login_with_correct_password(auth, super_admin):
    result = auth.authenticate("owner", "Secret123")
    assert result.principal.username == "owner"
    assert result.principal.role == ROLE_SUPER_ADMIN


def test_login_username_is_case_insensitive(auth, super_admin):
    assert auth.authenticate("OWNER", "Secret123").principal.username == "owner"


def test_login_with_persian_digits_in_username_is_normalized(auth):
    auth.create_user("user1", "کاربر", "Secret123", ROLE_VIEWER)
    # A Persian/Arabic digit keyboard must still work for an ASCII username.
    assert auth.authenticate("user۱", "Secret123").principal.username == "user1"


def test_login_with_wrong_password(auth, super_admin):
    with pytest.raises(AuthError) as exc:
        auth.authenticate("owner", "wrong-password")
    assert exc.value.code == "invalid_credentials"
    assert exc.value.message == MSG_INVALID_CREDENTIALS


def test_login_with_unknown_user(auth, super_admin):
    with pytest.raises(AuthError) as exc:
        auth.authenticate("ghost", "Secret123")
    assert exc.value.code == "invalid_credentials"


def test_login_with_empty_fields(auth):
    with pytest.raises(AuthError):
        auth.authenticate("", "")
    with pytest.raises(AuthError):
        auth.authenticate("owner", "")


def test_login_of_disabled_user(auth, super_admin, store):
    auth.create_user("off", "غیرفعال", "Secret123", ROLE_OPERATOR, is_active=False)
    with pytest.raises(AuthError) as exc:
        auth.authenticate("off", "Secret123")
    assert exc.value.code == "user_disabled"
    assert exc.value.message == MSG_USER_DISABLED


def test_user_is_locked_after_five_wrong_passwords(auth, super_admin):
    auth.create_user("lockme", "قفل", "Secret123", ROLE_OPERATOR)
    for attempt in range(MAX_FAILED_ATTEMPTS - 1):
        with pytest.raises(AuthError) as exc:
            auth.authenticate("lockme", "nope")
        assert exc.value.code == "invalid_credentials", attempt
    # The fifth failure locks the account.
    with pytest.raises(AuthError) as exc:
        auth.authenticate("lockme", "nope")
    assert exc.value.code == "user_locked"
    assert exc.value.message == MSG_USER_LOCKED
    # Even the correct password is refused while locked.
    with pytest.raises(AuthError) as exc:
        auth.authenticate("lockme", "Secret123")
    assert exc.value.code == "user_locked"


def test_a_successful_login_resets_the_failure_counter(auth, super_admin, store):
    auth.create_user("flaky", "نوسانی", "Secret123", ROLE_OPERATOR)
    for _ in range(3):
        with pytest.raises(AuthError):
            auth.authenticate("flaky", "nope")
    auth.authenticate("flaky", "Secret123")
    row = store.get_admin_user_by_username("flaky")
    assert row["failed_attempts"] == 0
    assert row["last_login_at"] is not None


def test_lock_expires_and_login_works_again(auth, super_admin, store):
    from datetime import datetime, timedelta, timezone

    auth.create_user("expired", "منقضی", "Secret123", ROLE_OPERATOR)
    row = store.get_admin_user_by_username("expired")
    past = (datetime.now(timezone.utc) - timedelta(minutes=LOCK_MINUTES + 1)).isoformat()
    store.update_admin_user(row["id"], is_active=True)
    with store._cursor() as cur:  # simulate an expired lock
        cur.execute("UPDATE admin_users SET locked_until=? WHERE id=?", (past, row["id"]))
    assert auth.authenticate("expired", "Secret123").principal.username == "expired"


def test_login_is_audited(auth, super_admin, store):
    auth.authenticate("owner", "Secret123")
    actions = [row["action"] for row in store.list_audit()]
    assert "login" in actions
    assert all("Secret123" not in row["detail"] for row in store.list_audit())


# ---- user management ------------------------------------------------------
def test_create_user_validation(auth, super_admin):
    with pytest.raises(AuthError) as exc:
        auth.create_user("ab", "کوتاه", "Secret123", ROLE_OPERATOR)
    assert exc.value.code == "username_invalid"
    with pytest.raises(AuthError) as exc:
        auth.create_user("bad name!", "فاصله", "Secret123", ROLE_OPERATOR)
    assert exc.value.code == "username_invalid"
    with pytest.raises(AuthError) as exc:
        auth.create_user("okname", "  ", "Secret123", ROLE_OPERATOR)
    assert exc.value.code == "name_required"
    with pytest.raises(AuthError) as exc:
        auth.create_user("okname", "نام", "Secret123", "wizard")
    assert exc.value.code == "role_invalid"
    with pytest.raises(AuthError) as exc:
        auth.create_user("okname", "نام", "123", ROLE_OPERATOR)
    assert exc.value.code == "weak_password"


def test_duplicate_username_is_rejected_with_persian_message(auth, super_admin):
    auth.create_user("staff", "کارمند", "Secret123", ROLE_OPERATOR)
    with pytest.raises(AuthError) as exc:
        auth.create_user("STAFF", "دوباره", "Secret123", ROLE_OPERATOR)
    assert exc.value.message == MSG_USERNAME_TAKEN


def test_cannot_demote_the_last_active_super_admin(auth, super_admin):
    with pytest.raises(AuthError) as exc:
        auth.update_user(super_admin.user_id, role=ROLE_VIEWER, actor="owner")
    assert exc.value.message == MSG_LAST_SUPER_ADMIN


def test_can_demote_a_super_admin_when_another_exists(auth, super_admin):
    second = auth.create_user("owner2", "مالک دوم", "Secret123", ROLE_SUPER_ADMIN)
    updated = auth.update_user(second.user_id, role=ROLE_ADMIN, actor="owner")
    assert updated.role == ROLE_ADMIN


def test_cannot_deactivate_or_delete_self(auth, super_admin):
    with pytest.raises(AuthError) as exc:
        auth.update_user(super_admin.user_id, is_active=False, actor="owner",
                         actor_id=super_admin.user_id)
    assert exc.value.message == MSG_CANNOT_DEACTIVATE_SELF
    with pytest.raises(AuthError) as exc:
        auth.delete_user(super_admin.user_id, actor="owner", actor_id=super_admin.user_id)
    assert exc.value.message == MSG_CANNOT_DELETE_SELF


def test_cannot_delete_the_last_super_admin(auth, super_admin):
    with pytest.raises(AuthError) as exc:
        auth.delete_user(super_admin.user_id, actor="someone-else", actor_id=999)
    assert exc.value.message == MSG_LAST_SUPER_ADMIN


def test_delete_other_user(auth, super_admin, store):
    victim = auth.create_user("victim", "قربانی", "Secret123", ROLE_VIEWER)
    auth.delete_user(victim.user_id, actor="owner", actor_id=super_admin.user_id)
    assert store.get_admin_user(victim.user_id) is None


def test_reset_password_lets_the_user_log_in(auth, super_admin):
    created = auth.create_user("staff", "کارمند", "Secret123", ROLE_OPERATOR)
    auth.reset_password(created.user_id, "NewSecret1", actor="owner")
    assert auth.authenticate("staff", "NewSecret1").principal.username == "staff"
    with pytest.raises(AuthError):
        auth.authenticate("staff", "Secret123")


def test_reset_password_rejects_a_weak_password(auth, super_admin):
    created = auth.create_user("staff", "کارمند", "Secret123", ROLE_OPERATOR)
    with pytest.raises(AuthError):
        auth.reset_password(created.user_id, "123", actor="owner")


# ---- change own password --------------------------------------------------
def test_change_own_password_flow(auth, super_admin):
    with pytest.raises(AuthError) as exc:
        auth.change_own_password(super_admin.user_id, "wrong", "NewSecret1", "NewSecret1")
    assert exc.value.message == MSG_WRONG_CURRENT_PASSWORD
    with pytest.raises(AuthError) as exc:
        auth.change_own_password(super_admin.user_id, "Secret123", "NewSecret1", "Other123")
    assert exc.value.message == MSG_PASSWORD_MISMATCH
    auth.change_own_password(super_admin.user_id, "Secret123", "NewSecret1", "NewSecret1")
    assert auth.authenticate("owner", "NewSecret1").principal.username == "owner"


# ---- role permissions -----------------------------------------------------
def test_viewer_cannot_approve_payments_or_manage_users():
    assert has_permission(ROLE_VIEWER, ORDERS_APPROVE_PAYMENT) is False
    assert has_permission(ROLE_VIEWER, USERS_MANAGE) is False
    assert has_permission(ROLE_VIEWER, SETTINGS_EDIT_CONNECTION) is False


def test_operator_cannot_approve_payments():
    assert has_permission(ROLE_OPERATOR, ORDERS_APPROVE_PAYMENT) is False
    assert has_permission(ROLE_OPERATOR, "customers.approve") is False
    assert has_permission(ROLE_OPERATOR, "orders.upload_receipt") is True


def test_admin_can_approve_but_not_manage_users_or_the_api_key():
    assert has_permission(ROLE_ADMIN, ORDERS_APPROVE_PAYMENT) is True
    assert has_permission(ROLE_ADMIN, "customers.approve") is True
    assert has_permission(ROLE_ADMIN, USERS_MANAGE) is False
    assert has_permission(ROLE_ADMIN, SETTINGS_EDIT_CONNECTION) is False


def test_super_admin_can_do_everything_an_admin_can_plus_users():
    admin_perms = role_permissions(ROLE_ADMIN)
    super_perms = role_permissions(ROLE_SUPER_ADMIN)
    assert admin_perms.issubset(super_perms)
    assert has_permission(ROLE_SUPER_ADMIN, USERS_MANAGE) is True
    assert has_permission(ROLE_SUPER_ADMIN, SETTINGS_EDIT_CONNECTION) is True


def test_unknown_role_has_no_permissions():
    assert role_permissions("wizard") == frozenset()
    assert has_permission(None, ORDERS_APPROVE_PAYMENT) is False


def test_principal_can_helper(super_admin, make_user):
    assert super_admin.can(USERS_MANAGE) is True
    operator = make_user(role=ROLE_OPERATOR)
    assert operator.can(ORDERS_APPROVE_PAYMENT) is False
    assert operator.can("orders.view") is True


def test_every_role_message_is_persian():
    import re

    from app.statuses import ROLE_DESCRIPTION_FA

    for role in (ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER):
        assert re.search(r"[\u0600-\u06FF]", ROLE_DESCRIPTION_FA[role])


# ---- AuthService constructor sanity ---------------------------------------
def test_auth_service_needs_first_admin_when_store_is_empty(store):
    service = AuthService(store)
    assert service.needs_first_super_admin is True
