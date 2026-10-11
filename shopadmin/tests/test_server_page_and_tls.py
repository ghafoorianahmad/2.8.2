"""The super admin's server page, and certificate pinning against a real HTTPS server."""
from __future__ import annotations

import datetime as dt
import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("cryptography")

from app.api_client import (  # noqa: E402
    MSG_TLS_MISMATCH,
    MSG_TLS_NOT_PINNED,
    ApiError,
    ShopApiClient,
    fetch_server_certificate,
    fingerprint_of_pem,
    short_fingerprint,
)
from app.auth import AuthService  # noqa: E402
from app.statuses import ROLE_ADMIN, ROLE_SUPER_ADMIN  # noqa: E402
from app.store import Store  # noqa: E402
from app.ui.context import AppContext  # noqa: E402

from .conftest import OWNER_PASSWORD, make_client  # noqa: E402


def _pump(app, ms: int = 5000) -> None:
    from PySide6.QtCore import QThreadPool

    for _ in range(10):
        app.processEvents()
    QThreadPool.globalInstance().waitForDone(ms)
    for _ in range(30):
        app.processEvents()


# --------------------------------------------------------------------------
# server page
# --------------------------------------------------------------------------
@pytest.fixture
def server_context(tmp_path, fake_api, admin_qapp):
    store = Store(tmp_path / "srv.db")
    store.configure_connection("http://shopapi.test")
    client = make_client(fake_api)
    auth = AuthService(store, client)
    principal = auth.authenticate("owner", OWNER_PASSWORD).principal
    context = AppContext(store=store, auth=auth, api=client, principal=principal)
    yield context
    client.close()
    store.close()


def _open_page(context, admin_qapp):
    from app.ui.pages.server import ServerPage

    page = ServerPage(context)
    page.show()
    page.refresh()
    _pump(admin_qapp)
    return page


def test_server_page_shows_status(server_context, admin_qapp, fake_api):
    page = _open_page(server_context, admin_qapp)
    try:
        assert "متصل" in page.status_labels["accounting"].text()
        assert "آزمایشی" in page.status_labels["write"].text()
        assert "بله: فعال" in page.status_labels["bots"].text()
        assert "۱ روز" in page.status_labels["uptime"].text()
        assert page.fingerprint_short.text() == "ABAB ABAB ABAB ABAB"
        assert page.restart_button.isEnabled()
    finally:
        page.close()


def test_secrets_are_never_prefilled(server_context, admin_qapp):
    page = _open_page(server_context, admin_qapp)
    try:
        token_field = page._inputs["BALE_TOKEN"]
        assert token_field.text() == ""
        assert "تنظیم شده" in token_field.placeholderText()
        assert "TELEGRAM_TOKEN" not in page._inputs
        assert page._inputs["BANK_ACCOUNT_TEXT"].text() == "حساب قدیم"
    finally:
        page.close()


def test_only_changed_values_are_sent(server_context, admin_qapp, fake_api, monkeypatch):
    from app.ui import widgets

    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: False)  # no restart now
    page = _open_page(server_context, admin_qapp)
    try:
        page._inputs["BANK_ACCOUNT_TEXT"].setText("حساب جدید")
        page._inputs["BALE_TOKEN"].setText("555:new-token")
        page._save_settings()
        _pump(admin_qapp)
        assert fake_api.settings_puts == [{"BANK_ACCOUNT_TEXT": "حساب جدید",
                                           "BALE_TOKEN": "555:new-token"}]
        assert "ذخیره شد" in page.settings_message.text()
    finally:
        page.close()


def test_invalid_setting_is_explained_in_persian(server_context, admin_qapp, fake_api):
    page = _open_page(server_context, admin_qapp)
    try:
        page._inputs["RESERVE_HOURS"].setText("abc")
        page._save_settings()
        _pump(admin_qapp)
        text = page.settings_message.text()
        assert "مهلت پرداخت" in text and "۱" in text and "۱۶۸" in text
        assert fake_api.settings_puts == []
    finally:
        page.close()


def test_restart_asks_first(server_context, admin_qapp, fake_api, monkeypatch):
    from app.ui import widgets

    answers = iter([False, True])
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: next(answers))
    page = _open_page(server_context, admin_qapp)
    try:
        page._restart()
        _pump(admin_qapp)
        assert fake_api.restarts == 0
        page._restart()
        _pump(admin_qapp)
        assert fake_api.restarts == 1
    finally:
        page.close()


def test_log_viewer(server_context, admin_qapp):
    page = _open_page(server_context, admin_qapp)
    try:
        page._load_log()
        _pump(admin_qapp)
        assert "ready" in page.log_view.toPlainText()
    finally:
        page.close()


def test_server_page_is_super_admin_only(server_context, admin_qapp):
    from app.permissions import Principal
    from app.ui.main_window import MainWindow

    server_context.principal = Principal(1, "boss", "مدیر فروش", ROLE_ADMIN)
    window = MainWindow(server_context)
    try:
        assert "server" not in window._nav_buttons
    finally:
        window.close()
    server_context.principal = Principal(1, "owner", "مالک", ROLE_SUPER_ADMIN)
    window = MainWindow(server_context)
    try:
        assert "server" in window._nav_buttons
    finally:
        window.close()


# --------------------------------------------------------------------------
# TLS pinning against a real local HTTPS server
# --------------------------------------------------------------------------
def _make_cert(tmp_path, name: str):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=1))
            .not_valid_after(now + dt.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(key, hashes.SHA256()))
    cert_file, key_file = tmp_path / f"{name}.crt", tmp_path / f"{name}.key"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                           serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return cert_file, key_file


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = {"/health": {"status": "ok"}, "/auth/status": {"bootstrap_required": False}}.get(
            self.path.split("?")[0], {"detail": "Not Found"})
        data = json.dumps(body).encode()
        self.send_response(200 if "detail" not in body else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def https_server(tmp_path):
    cert_file, key_file = _make_cert(tmp_path, "server")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"https://127.0.0.1:{server.server_address[1]}", cert_file.read_text()
    server.shutdown()


def test_fetch_and_pin_the_server_certificate(https_server):
    url, real_pem = https_server
    pem, fingerprint = fetch_server_certificate(url)
    assert fingerprint == fingerprint_of_pem(real_pem)
    assert len(short_fingerprint(fingerprint).split()) == 4
    client = ShopApiClient(url, server_cert_pem=pem, timeout=5)
    try:
        assert client.probe_server() == {"bootstrap_required": False}
    finally:
        client.close()


def test_a_different_certificate_is_refused(https_server, tmp_path):
    url, _real = https_server
    other_cert, _key = _make_cert(tmp_path, "impostor")
    client = ShopApiClient(url, server_cert_pem=other_cert.read_text(), timeout=5)
    try:
        with pytest.raises(ApiError) as exc:
            client.health()
        assert exc.value.kind == "tls"
        assert exc.value.message == MSG_TLS_MISMATCH
    finally:
        client.close()


def test_https_without_a_pin_is_refused_before_connecting(https_server):
    url, _real = https_server
    client = ShopApiClient(url, timeout=5)
    try:
        with pytest.raises(ApiError) as exc:
            client.health()
        assert exc.value.message == MSG_TLS_NOT_PINNED
    finally:
        client.close()


def test_wizard_requires_the_fingerprint_confirmation(https_server, tmp_path, admin_qapp):
    from app.ui.wizard import SetupWizard

    url, real_pem = https_server
    store = Store(tmp_path / "wiz_tls.db")
    auth = AuthService(store, ShopApiClient())
    wizard = SetupWizard(store, auth)
    try:
        done = []
        wizard.finished.connect(lambda: done.append(True))
        wizard._step = 1
        wizard._update_step()
        wizard.base_url_input.setText(url)
        wizard._next()
        _pump(admin_qapp)
        assert done == []  # not confirmed yet
        assert "اثرانگشت" in wizard.connection_result.text()
        assert wizard.cert_box.isVisibleTo(wizard), wizard.connection_result.text()
        assert wizard.fingerprint_full.text() == fingerprint_of_pem(real_pem)

        wizard.cert_confirm.setChecked(True)
        wizard._next()
        _pump(admin_qapp)
        assert done == [True]
        assert store.server_cert_pem.strip() == real_pem.strip()
        assert store.base_url == url
    finally:
        wizard.close()
        store.close()
