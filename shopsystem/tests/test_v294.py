"""v2.9.4: the data folder chosen in the installer (registry), its safe move
(copy + SHA-256, switch, health check, only then delete; any failure = back to
the old folder with nothing deleted), and the setup helpers' JSON."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

import launcher


def test_data_folder_comes_from_the_installer_choice(tmp_path, monkeypatch):
    chosen = tmp_path / "ShopServerData"
    monkeypatch.delenv("SHOPSERVER_DATA_DIR", raising=False)
    monkeypatch.setattr(launcher, "APP_DIR", tmp_path / "app")
    monkeypatch.setattr(launcher, "registered_data_dir", lambda: chosen)
    assert launcher.resolve_data_dir([]) == chosen
    monkeypatch.setattr(launcher, "registered_data_dir", lambda: None)
    assert launcher.resolve_data_dir([]) == launcher.DEFAULT_DATA_DIR
    assert launcher.resolve_data_dir(["--data-dir", str(tmp_path / "x")]) == \
        (tmp_path / "x").resolve()


def _data(folder: Path) -> Path:
    (folder / "tls").mkdir(parents=True)
    (folder / ".env").write_text("A=1\n", encoding="utf-8")
    (folder / "shopapi.db").write_bytes(b"db" * 1000)
    (folder / "tls" / "server.crt").write_text("cert", encoding="utf-8")
    (folder / "left.tmp").write_text("x", encoding="utf-8")
    return folder


def test_copy_is_verified_file_by_file(tmp_path):
    source = _data(tmp_path / "old")
    count = launcher.copy_verified(source, tmp_path / "new")
    assert count == 3                                     # *.tmp is not carried over
    assert (tmp_path / "new" / "tls" / "server.crt").read_text(encoding="utf-8") == "cert"
    assert not (tmp_path / "new" / "left.tmp").exists()


class FakeService(types.ModuleType):
    def __init__(self, running=True):
        super().__init__("winservice")
        self.running = running
        self.installed_for: list[Path] = []
        self.calls: list[str] = []

    def exists(self, run=None):
        return True

    def state(self, run=None):
        return "running" if self.running else "stopped"

    def stop(self, run=None):
        self.calls.append("stop")
        self.running = False

    def start(self, run=None):
        self.calls.append("start")
        self.running = True

    def install(self, exe, data_dir, **kw):
        self.installed_for.append(Path(data_dir))
        return {"ok": True}

    def local_backup_dir(self, raw):
        return None


@pytest.fixture
def mover(tmp_path, monkeypatch, capsys):
    service = FakeService()
    monkeypatch.setitem(sys.modules, "winservice", service)
    registry: list[Path] = []
    monkeypatch.setattr(launcher, "register_data_dir", lambda folder: registry.append(Path(folder)))
    monkeypatch.setattr(launcher, "registered_data_dir", lambda: None)
    monkeypatch.setattr(launcher, "harden_folder", lambda folder, run=None: None)
    monkeypatch.setattr(launcher, "read_env_values", lambda: {})
    old = _data(tmp_path / "ProgramData" / "ShopServer")
    launcher.configure_paths(old)

    def run(target: Path, healthy: bool) -> dict:
        code = launcher.move_data(str(target), health=lambda timeout: healthy)
        answer = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        answer["code"] = code
        return answer

    return types.SimpleNamespace(service=service, registry=registry, old=old, run=run)


def test_move_deletes_the_old_folder_only_after_the_server_answers(mover, tmp_path):
    target = tmp_path / "D" / "ShopServerData"
    answer = mover.run(target, healthy=True)
    assert answer["ok"] and answer["moved"] and answer["old_removed"] and answer["code"] == 0
    assert (target / ".env").read_text(encoding="utf-8") == "A=1\n"
    assert not mover.old.exists()
    assert mover.registry == [target]
    assert mover.service.installed_for == [target] and mover.service.running


def test_failed_move_goes_back_and_deletes_nothing(mover, tmp_path):
    target = tmp_path / "D" / "ShopServerData"
    answer = mover.run(target, healthy=False)
    assert answer["ok"] is False and answer["code"] == 1
    assert "هیچ داده‌ای پاک نشد" in answer["message_fa"]
    assert (mover.old / ".env").exists() and (mover.old / "shopapi.db").exists()
    assert mover.registry[-1] == mover.old                    # pointed back
    assert mover.service.installed_for[-1] == mover.old and mover.service.running


def test_move_refuses_a_folder_with_files(mover, tmp_path):
    target = tmp_path / "busy"
    target.mkdir()
    (target / "x.txt").write_text("x", encoding="utf-8")
    answer = mover.run(target, healthy=True)
    assert answer["ok"] is False and answer["error"] == "not_empty"
    assert (mover.old / ".env").exists() and mover.registry == []


def test_fresh_install_only_remembers_the_folder(tmp_path, monkeypatch, capsys):
    registry = []
    monkeypatch.setitem(sys.modules, "winservice", FakeService())
    monkeypatch.setattr(launcher, "register_data_dir", lambda folder: registry.append(Path(folder)))
    launcher.configure_paths(tmp_path / "empty")
    assert launcher.move_data(str(tmp_path / "D" / "Data")) == 0
    assert registry == [tmp_path / "D" / "Data"]
    assert json.loads(capsys.readouterr().out.strip())["moved"] is False


def test_list_dbs_reads_the_password_from_stdin(tmp_path, monkeypatch, capsys):
    # the server package as bundled by build_exe.bat (skipped before the first build)
    monkeypatch.syspath_prepend(str(Path(launcher.__file__).resolve().parent / "build_src"))
    pytest.importorskip("shopapi_app.db_setup")
    from shopapi_app import db_setup

    seen = {}

    def fake(settings, connect=None):
        seen["user"], seen["password"] = settings.accounting_username, settings.accounting_password
        return {"ok": True, "databases": ["hesab5"]}

    monkeypatch.setattr(db_setup, "list_databases", fake)
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(read=lambda: json.dumps(
        {"server": ".", "user": "shopbot", "password": "S3cret"})))
    assert launcher.main(["--data-dir", str(tmp_path), "--list-dbs"]) == 0
    out = capsys.readouterr().out
    assert "S3cret" not in out and json.loads(out.strip())["databases"] == ["hesab5"]
    assert seen == {"user": "shopbot", "password": "S3cret"}
