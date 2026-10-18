"""Sign-in and staff management through the server (fake shopapi, no network)."""
from __future__ import annotations

import pytest

from app.auth import (
    MSG_EMPTY_FIELDS,
    MSG_PASSWORD_LETTERS_DIGITS,
    MSG_PASSWORD_MISMATCH,
    MSG_PASSWORD_TOO_SHORT,
    MSG_USERNAME_INVALID,
    AuthError,
    AuthService,
    validate_password_strength,
)
from app.statuses import ROLE_ADMIN, ROLE_OPERATOR, ROLE_SUPER_ADMIN, ROLE_VIEWER

from .conftest import OWNER_PASSWORD, SERVICE_KEY, FakeShopApi, make_client


def signed_in(auth: AuthService, username="owner", password=OWNER_PASSWORD):
    return auth.authenticate(username, password)


# ---- password policy (mirrors the server) ----------------------------------
@pytest.mark.parametrize("password, message", [
    ("Ab1", MSG_PASSWORD_TOO_SHORT),
    ("abcdefgh", MSG_PASSWORD_LETTERS_DIGITS),
    ("12345678", MSG_PASSWORD_LETTERS_DIGITS),
    ("Secret123", None),
    ("رمزعبور۱۲۳۴", None),
])
def test_password_policy(password, message):
    assert validate_password_strength(password) == message


# ---- login -------------------------------------------------------------------
def test_login_returns_the_server_account(auth, fake_api):
    result = signed_in(auth)
    assert result.principal.username == "owner"
    assert result.principal.role == ROLE_SUPER_ADMIN
    assert result.must_change_password is False
    assert auth.api.token  # the session token is kept for later calls


def test_password_goes_only_to_the_login_endpoint(auth, fake_api):
    signed_in(auth)
    assert fake_api.requests[-1] == ("POST", "/auth/login")
    assert fake_api.login_bodies[-1]["password"] == OWNER_PASSWORD
    assert fake_api.login_bodies[-1]["client"]  # the computer name is reported


def test_persian_digits_in_the_username_are_normalized(auth, fake_api):
    fake_api.add_staff("user1", OWNER_PASSWORD, ROLE_VIEWER)
    assert auth.authenticate("user۱", OWNER_PASSWORD).principal.username == "user1"


def test_wrong_password_is_reported_in_persian(auth):
    with pytest.raises(AuthError) as exc:
        auth.authenticate("owner", "wrong-password1")
    assert exc.value.code == "invalid_credentials"
    assert "نادرست" in exc.value.message


def test_unknown_user_gets_the_same_message(auth):
    with pytest.raises(AuthError) as a:
        auth.authenticate("owner", "wrong-password1")
    with pytest.raises(AuthError) as b:
        auth.authenticate("ghost", "wrong-password1")
    assert a.value.message == b.value.message


def test_empty_fields_never_reach_the_server(auth, fake_api):
    before = len(fake_api.requests)
    with pytest.raises(AuthError) as exc:
        auth.authenticate("", "")
    assert exc.value.message == MSG_EMPTY_FIELDS
    assert len(fake_api.requests) == before


def test_disabled_account(auth, fake_api):
    fake_api.add_staff("off", OWNER_PASSWORD, ROLE_OPERATOR, active=False)
    with pytest.raises(AuthError) as exc:
        auth.authenticate("off", OWNER_PASSWORD)
    assert "غیرفعال" in exc.value.message


def test_lockout_is_decided_by_the_server(auth):
    for _ in range(5):
        with pytest.raises(AuthError):
            auth.authenticate("owner", "wrong-password1")
    with pytest.raises(AuthError) as exc:
        auth.authenticate("owner", OWNER_PASSWORD)
    assert exc.value.code == "user_locked"
    assert "قفل" in exc.value.message


def test_offline_server_is_explained(auth, fake_api):
    fake_api.offline = True
    with pytest.raises(AuthError) as exc:
        auth.authenticate("owner", OWNER_PASSWORD)
    assert exc.value.code == "offline"


def test_must_change_password_flag_is_passed_on(auth, fake_api):
    fake_api.add_staff("temp", OWNER_PASSWORD, ROLE_ADMIN, must_change=True)
    assert auth.authenticate("temp", OWNER_PASSWORD).must_change_password is True


def test_logout_ends_the_server_session(auth, fake_api):
    signed_in(auth)
    token = auth.api.token
    auth.logout()
    assert auth.api.token == ""
    assert token not in fake_api.tokens


# ---- bootstrap ---------------------------------------------------------------
def test_first_admin_is_created_on_the_server(store, tmp_path):
    fake = FakeShopApi()
    client = make_client(fake, token="")
    auth = AuthService(store, client)
    assert auth.server_needs_first_admin() is True
    principal = auth.create_first_super_admin(SERVICE_KEY, "owner", "مالک", "Secret123")
    assert principal.role == ROLE_SUPER_ADMIN
    assert auth.server_needs_first_admin() is False
    with pytest.raises(AuthError):
        auth.create_first_super_admin(SERVICE_KEY, "second", "دوم", "Secret123")
    client.close()


def test_bootstrap_with_a_wrong_service_key(store):
    fake = FakeShopApi()
    client = make_client(fake, token="")
    auth = AuthService(store, client)
    with pytest.raises(AuthError):
        auth.create_first_super_admin("nope", "owner", "مالک", "Secret123")
    assert fake.staff == {}
    client.close()


def test_bootstrap_validates_before_calling_the_server(store):
    fake = FakeShopApi()
    client = make_client(fake, token="")
    auth = AuthService(store, client)
    with pytest.raises(AuthError) as exc:
        auth.create_first_super_admin(SERVICE_KEY, "a b", "مالک", "Secret123")
    assert exc.value.message == MSG_USERNAME_INVALID
    assert fake.requests == []
    client.close()


# ---- own password --------------------------------------------------------------
def test_change_own_password(auth, fake_api):
    signed_in(auth)
    auth.change_own_password(OWNER_PASSWORD, "NewSecret1", "NewSecret1")
    assert fake_api.find_staff("owner")["password"] == "NewSecret1"


def test_change_own_password_checks(auth):
    signed_in(auth)
    with pytest.raises(AuthError) as exc:
        auth.change_own_password(OWNER_PASSWORD, "NewSecret1", "Other1234")
    assert exc.value.message == MSG_PASSWORD_MISMATCH
    with pytest.raises(AuthError):
        auth.change_own_password(OWNER_PASSWORD, "short1", "short1")
    with pytest.raises(AuthError) as exc:
        auth.change_own_password("WrongOld1", "NewSecret1", "NewSecret1")
    assert "فعلی" in exc.value.message


# ---- staff management ------------------------------------------------------------
def test_super_admin_manages_staff(auth, fake_api):
    signed_in(auth)
    created = auth.create_user("clerk", "کارمند", "Secret123", ROLE_OPERATOR)
    assert fake_api.find_staff("clerk")["must_change_password"] is True
    auth.update_user(created.user_id, role=ROLE_SUPER_ADMIN)        # v2.7.0: «مدیر»
    assert fake_api.find_staff("clerk")["role"] == ROLE_SUPER_ADMIN
    auth.reset_password(created.user_id, "Fresh7890")
    assert fake_api.find_staff("clerk")["password"] == "Fresh7890"
    usernames = {row["username"] for row in auth.list_users()}
    assert usernames == {"owner", "clerk"}
    auth.delete_user(created.user_id)
    assert fake_api.find_staff("clerk") is None


def test_create_user_validates_locally(auth, fake_api):
    signed_in(auth)
    for args, code in (
        (("ab", "کوتاه", "Secret123", ROLE_OPERATOR), "username_invalid"),
        (("okname", "  ", "Secret123", ROLE_OPERATOR), "name_required"),
        (("okname", "نام", "Secret123", "wizard"), "role_invalid"),
        (("okname", "نام", "123", ROLE_OPERATOR), "weak_password"),
    ):
        with pytest.raises(AuthError) as exc:
            auth.create_user(*args)
        assert exc.value.code == code


def test_duplicate_username_comes_back_from_the_server(auth):
    signed_in(auth)
    auth.create_user("staff", "کارمند", "Secret123", ROLE_OPERATOR)
    with pytest.raises(AuthError) as exc:
        auth.create_user("STAFF", "دوباره", "Secret123", ROLE_OPERATOR)
    assert "قبلاً" in exc.value.message


def test_last_super_admin_is_protected_by_the_server(auth, super_admin):
    signed_in(auth)
    with pytest.raises(AuthError) as exc:
        auth.update_user(super_admin.user_id, role=ROLE_OPERATOR)
    assert "مدیر" in exc.value.message


def test_cannot_deactivate_or_delete_self(auth, super_admin):
    signed_in(auth)
    with pytest.raises(AuthError):
        auth.update_user(super_admin.user_id, is_active=False, actor_id=super_admin.user_id)
    with pytest.raises(AuthError):
        auth.delete_user(super_admin.user_id)


def test_a_non_super_admin_is_refused_by_the_server(auth, fake_api):
    fake_api.add_staff("boss", OWNER_PASSWORD, ROLE_ADMIN)
    auth.authenticate("boss", OWNER_PASSWORD)
    with pytest.raises(AuthError) as exc:
        auth.list_users()
    assert exc.value.code == "forbidden"


def test_unlock(auth, fake_api):
    signed_in(auth)
    row = fake_api.add_staff("stuck", OWNER_PASSWORD, ROLE_OPERATOR)
    row["locked"] = True
    auth.unlock_user(row["id"])
    assert fake_api.find_staff("stuck")["locked"] is False


# ---- session loss ---------------------------------------------------------------
def test_a_revoked_session_triggers_the_callback(api, fake_api):
    calls = []
    api.on_session_invalid = lambda: calls.append(True)
    fake_api.tokens.clear()  # e.g. the owner's role was changed elsewhere
    from app.api_client import ApiAuthError

    with pytest.raises(ApiAuthError):
        api.list_customers()
    assert calls == [True]
    assert api.token == ""
