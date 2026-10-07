"""Server setup steps, with Windows commands captured instead of executed."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from app import server_setup as setup


@pytest.fixture
def captured(tmp_path, monkeypatch):
    """Redirect the data folder and record every Windows command."""
    commands: list[list[str]] = []

    class Done:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        commands.append(list(command))
        return Done()

    monkeypatch.setattr(setup, "data_dir", lambda: tmp_path / "ShopServer")
    monkeypatch.setattr(setup, "_run", fake_run)
    monkeypatch.setattr(setup, "server_command",
                        lambda: [r"C:\Program Files\ShopServer\ShopSystem\ShopSystem.exe"])
    (tmp_path / "ShopServer").mkdir()
    return commands


def test_data_folder_is_locked_to_system_and_administrators_by_sid(captured):
    setup.harden_data_dir()
    command = captured[0]
    assert command[0] == "icacls" and "/inheritance:r" in command
    assert "*S-1-5-18:(OI)(CI)F" in command          # SYSTEM, any Windows language
    assert "*S-1-5-32-544:(OI)(CI)F" in command      # Administrators
    grants = [part for part in command if ":(" in part]
    assert len(grants) == 2  # nobody else (no Users / Everyone)


def test_hardening_never_recurses_with_grants_and_resets_existing_files(captured, tmp_path):
    (tmp_path / "ShopServer" / ".env").write_text("A=1\n", encoding="utf-8")
    setup.harden_data_dir()
    assert "/T" not in captured[0]               # /T + (OI)(CI) emptied the ACL of .env
    resets = [c for c in captured if "/reset" in c]
    assert [c[1] for c in resets] == [str(tmp_path / "ShopServer" / ".env")]


def test_hardening_creates_missing_folder_and_is_repeatable(captured, tmp_path, monkeypatch):
    folder = tmp_path / "fresh" / "ShopServer"
    monkeypatch.setattr(setup, "data_dir", lambda: folder)
    setup.harden_data_dir()
    setup.harden_data_dir()                      # second run after a partial success
    assert folder.is_dir()


def test_hardening_reports_the_real_error_when_env_is_unreadable(captured, tmp_path, monkeypatch):
    (tmp_path / "ShopServer" / ".env").write_text("A=1\n", encoding="utf-8")
    real_open = open

    def deny(path, *args, **kwargs):
        if str(path).endswith(".env"):
            raise PermissionError(13, "Permission denied", str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", deny)
    with pytest.raises(setup.SetupError) as exc:
        setup.harden_data_dir()
    assert "Permission denied" in exc.value.message


def test_icacls_failure_shows_its_output(monkeypatch, tmp_path):
    class Failed:
        returncode = 5
        stdout = ""
        stderr = "Access is denied."

    monkeypatch.setattr(setup, "data_dir", lambda: tmp_path / "ShopServer")
    monkeypatch.setattr(setup, "_run", lambda command, **kw: Failed())
    with pytest.raises(setup.SetupError) as exc:
        setup.harden_data_dir()
    assert "Access is denied" in exc.value.detail


def test_server_tool_crash_surfaces_the_real_exception(monkeypatch):
    class Crashed:
        returncode = 1
        stdout = b""
        stderr = (b"Traceback...\nPermissionError: [Errno 13] Permission denied: "
                  b"'C:\\\\ProgramData\\\\ShopServer\\\\.env'\n[PYI-1:ERROR] Failed\n")

    monkeypatch.setattr(setup, "server_command", lambda: ["x.exe"])
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: Crashed())
    with pytest.raises(setup.SetupError) as exc:
        setup.run_server_tool(["--check-db"])
    assert "PermissionError" in exc.value.message
    assert "قابل خواندن نبود" not in exc.value.message


def test_config_json_is_removed_even_when_the_tool_fails(captured, monkeypatch, tmp_path):
    def boom(args, timeout=60):
        raise setup.SetupError("x")

    monkeypatch.setattr(setup, "run_server_tool", boom)
    with pytest.raises(setup.SetupError):
        setup.write_config(setup.DatabaseConfig(".", "db", True), port=8443)
    assert list((tmp_path / "ShopServer").glob("setup-*.json")) == []


def test_task_runs_as_system_at_boot_and_restarts(captured):
    xml = setup.task_xml([r"C:\Program Files\ShopServer\ShopSystem\ShopSystem.exe"],
                         run_as_user=None)
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    root = ET.fromstring(xml.replace('encoding="UTF-16"', ""))
    assert root.find(".//t:BootTrigger", ns) is not None
    assert root.find(".//t:Principal/t:UserId", ns).text == "S-1-5-18"
    assert root.find(".//t:RestartOnFailure/t:Count", ns).text == "999"
    assert root.find(".//t:ExecutionTimeLimit", ns).text == "PT0S"
    assert root.find(".//t:MultipleInstancesPolicy", ns).text == "IgnoreNew"
    arguments = root.find(".//t:Exec/t:Arguments", ns).text
    assert "--service" in arguments and "--data-dir" in arguments


def test_task_for_a_windows_account_uses_a_password_logon(captured):
    xml = setup.task_xml(["x.exe"], run_as_user="SHOP\\owner")
    assert "<UserId>SHOP\\owner</UserId>" in xml
    assert "<LogonType>Password</LogonType>" in xml


def test_register_task_removes_the_xml_afterwards(captured, tmp_path):
    setup.register_task()
    create = next(c for c in captured if c[:2] == ["schtasks", "/Create"])
    assert create[create.index("/TN") + 1] == "ShopServer"
    assert not (tmp_path / "ShopServer" / "task.xml").exists()


def test_firewall_rule_is_local_network_only(captured):
    setup.open_firewall(8443)
    add = next(c for c in captured if "add" in c)
    assert "localport=8443" in add
    assert "remoteip=localsubnet" in add
    assert "profile=private,domain" in add
    assert any(part.startswith("program=") for part in add)


def test_config_password_never_goes_on_a_command_line(captured, monkeypatch, tmp_path):
    seen = {}

    def fake_tool(args, timeout=60):
        path = args[args.index("--init-config") + 1]
        seen["args"] = args
        seen["json"] = json.loads(open(path, encoding="utf-8").read())
        return {"ok": True}

    monkeypatch.setattr(setup, "run_server_tool", fake_tool)
    db = setup.DatabaseConfig(server=r".\SQLEXPRESS", database="hesab5", trusted=False,
                              user="shopbot", password="S3cret!pw")
    setup.write_config(db, port=8443, extra={"bank_account_text": "حساب", "bale_token": ""})
    assert "S3cret!pw" not in " ".join(seen["args"])
    assert seen["json"]["db_password"] == "S3cret!pw"
    assert seen["json"]["api_port"] == 8443 and seen["json"]["api_host"] == "0.0.0.0"
    assert "bale_token" not in seen["json"]  # empty optional values are left alone
    assert list((tmp_path / "ShopServer").glob("setup-*.json")) == []  # cleaned up


def test_windows_auth_sends_no_sql_credentials(captured, monkeypatch):
    seen = {}

    def fake_tool(args, timeout=60):
        seen["json"] = json.loads(open(args[args.index("--init-config") + 1],
                                       encoding="utf-8").read())
        return {"ok": True}

    monkeypatch.setattr(setup, "run_server_tool", fake_tool)
    setup.write_config(setup.DatabaseConfig(".", "db", True, "x", "y"), port=8443)
    assert seen["json"]["db_trusted"] is True
    assert seen["json"]["db_user"] == "" and seen["json"]["db_password"] == ""


def test_check_database_failure_is_persian(monkeypatch):
    monkeypatch.setattr(setup, "run_server_tool",
                        lambda args, timeout=60: {"ok": False, "error": "Error", "message": "x"})
    with pytest.raises(setup.SetupError) as exc:
        setup.check_database()
    assert "حسابداری" in exc.value.message


def test_service_key_is_read_from_the_locked_env(captured, tmp_path):
    (tmp_path / "ShopServer" / ".env").write_text("ADMIN_API_KEY=abc123\n", encoding="utf-8")
    assert setup.service_key() == "abc123"


def test_wizard_builds_and_validates_the_admin(admin_qapp, monkeypatch):
    monkeypatch.setattr(setup, "is_admin", lambda: True)
    monkeypatch.setattr(setup, "odbc_driver_installed", lambda driver=None: True)
    monkeypatch.setattr(setup, "network_is_public", lambda: False)
    monkeypatch.setattr(setup, "existing_config_port", lambda: None)
    from app.ui.server_setup_wizard import ServerSetupWizard

    wizard = ServerSetupWizard()
    try:
        assert wizard.port.value() == 8443
        wizard.admin_full_name.setText("مالک")
        wizard.admin_username.setText("owner")
        wizard.admin_password.setText("short")
        wizard.admin_confirm.setText("short")
        assert wizard._validate_admin() is False
        wizard.admin_password.setText("Owner1234")
        wizard.admin_confirm.setText("Owner1234")
        assert wizard._validate_admin() is True
    finally:
        wizard.close()
