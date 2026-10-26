"""Daily backup, restore test, encrypted off-server copy (Phase 5, REQUIREMENTS §10)."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import backup
import launcher
import winservice

PASS = "TEST-PASS-WORD-1234-ABCD-EFGH"
T0 = datetime(2026, 10, 12, 3, 0, tzinfo=timezone.utc)
LAUNCHER = Path(launcher.__file__).resolve()


def make_db(path: Path, rows: int, *, wal: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO orders (v) VALUES (?)", [(f"o{i}",) for i in range(rows)])
    conn.commit()
    return conn


@pytest.fixture
def data(tmp_path):
    root = tmp_path / "ShopServer"
    root.mkdir()
    (root / ".env").write_text("BALE_TOKEN=x\n", encoding="utf-8")
    (root / "messages.fa.json").write_text('{"hi": "سلام"}', encoding="utf-8")
    make_db(root / "shopapi.db", 5).close()
    make_db(root / "shopbots.db", 2).close()
    (root / "receipts").mkdir()
    (root / "receipts" / "order_1.jpg").write_bytes(b"\xff\xd8receipt")
    (root / "tls").mkdir()
    (root / "tls" / "server.pem").write_text("CERT", encoding="utf-8")
    (root / "shoptg").mkdir()
    (root / "shoptg" / "session.dpapi").write_bytes(b"secret session")
    (root / "app.log").write_text("log", encoding="utf-8")
    return root


def members(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as archive:
        return set(archive.namelist())


# ---- create / verify ------------------------------------------------------------
def test_backup_contents_and_verify(data, tmp_path):
    zip_path = backup.create_backup(data, tmp_path / "out", now=T0)
    assert zip_path.name == "ShopServer_20261012_030000.zip"
    names = members(zip_path)
    assert {".env", "messages.fa.json", "shopapi.db", "shopbots.db", "receipts/order_1.jpg",
            "tls/server.pem", "manifest.json"} == names
    assert not any("shoptg" in n or n.endswith(".log") for n in names)
    result = backup.verify_backup(zip_path)
    assert result["ok"] and result["rows"] == {"shopapi.db": 5, "shopbots.db": 2}


def test_live_wal_database_is_captured(data, tmp_path):
    (data / "shopapi.db").unlink()
    writer = make_db(data / "shopapi.db", 7, wal=True)   # open, rows still in the -wal file
    try:
        assert (data / "shopapi.db-wal").exists()
        zip_path = backup.create_backup(data, tmp_path / "out", now=T0)
    finally:
        writer.close()
    assert backup.verify_backup(zip_path)["rows"]["shopapi.db"] == 7


def test_tampered_backup_is_rejected(data, tmp_path):
    zip_path = backup.create_backup(data, tmp_path / "out", now=T0)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path) as src, zipfile.ZipFile(bad, "w") as dst:
        for item in src.infolist():
            payload = src.read(item.filename)
            if item.filename == "receipts/order_1.jpg":
                payload = b"changed"
            dst.writestr(item, payload)
    with pytest.raises(backup.BackupError, match="damaged"):
        backup.verify_backup(bad)
    (tmp_path / "junk.zip").write_bytes(b"not a zip")
    with pytest.raises(backup.BackupError):
        backup.verify_backup(tmp_path / "junk.zip")


# ---- encryption -----------------------------------------------------------------
@pytest.mark.parametrize("size", [0, 10, 64, 65, 300])
def test_encrypt_round_trip(tmp_path, monkeypatch, size):
    monkeypatch.setattr(backup, "CHUNK", 64)       # several chunks with tiny data
    plain = tmp_path / "p.bin"
    plain.write_bytes(os.urandom(size))
    enc, out = tmp_path / "p.ssbk", tmp_path / "back.bin"
    backup.encrypt_file(plain, enc, PASS)
    assert plain.read_bytes() not in enc.read_bytes() or size == 0
    backup.decrypt_file(enc, out, "test pass word 1234 abcd efgh".upper())  # spaces = hyphens
    assert out.read_bytes() == plain.read_bytes()


def test_wrong_passphrase_truncation_and_reorder(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "CHUNK", 64)
    plain = tmp_path / "p.bin"
    plain.write_bytes(os.urandom(200))
    enc = tmp_path / "p.ssbk"
    backup.encrypt_file(plain, enc, PASS)
    out = tmp_path / "o.bin"
    with pytest.raises(backup.BackupError, match="wrong passphrase"):
        backup.decrypt_file(enc, out, PASS.lower())          # case matters
    assert not out.exists() and not Path(str(out) + ".partial").exists()
    raw = enc.read_bytes()
    head, size = backup.HEADER.size, 64 + backup.TAG
    cut = tmp_path / "cut.ssbk"
    cut.write_bytes(raw[:head + 2 * size])                    # last chunk dropped
    with pytest.raises(backup.BackupError):
        backup.decrypt_file(cut, out, PASS)
    swapped = raw[:head] + raw[head + size:head + 2 * size] + raw[head:head + size] + raw[head + 2 * size:]
    (tmp_path / "sw.ssbk").write_bytes(swapped)
    with pytest.raises(backup.BackupError):
        backup.decrypt_file(tmp_path / "sw.ssbk", out, PASS)
    (tmp_path / "x.ssbk").write_bytes(b"hello")
    with pytest.raises(backup.BackupError, match="not a shop backup"):
        backup.decrypt_file(tmp_path / "x.ssbk", out, PASS)


def test_short_passphrase_refused(tmp_path):
    (tmp_path / "p").write_bytes(b"x")
    with pytest.raises(backup.BackupError, match="at least"):
        backup.encrypt_file(tmp_path / "p", tmp_path / "e", "short-pass")


# ---- daily job -------------------------------------------------------------------
def test_run_backup_without_passphrase_never_copies_plain(data, tmp_path):
    offsite = tmp_path / "usb"
    status = backup.run_backup(data, backup.BackupConfig(copy_dir=str(offsite)), now=T0)
    assert status["ok"] is False
    assert "BACKUP_PASSPHRASE" in status["offsite"]["error"]
    assert not offsite.exists() or not any(offsite.iterdir())
    assert status["file"] and status["verify"]["ok"]          # the local copy is fine
    assert backup.read_status(data)["ok"] is False


def test_run_backup_with_offsite_copy_and_prune(data, tmp_path):
    offsite = tmp_path / "usb"
    config = backup.BackupConfig(copy_dir=str(offsite), passphrase=PASS, keep_days=2)
    for day in range(3):
        status = backup.run_backup(data, config, now=T0 + timedelta(days=day))
        assert status["ok"], status
    assert len(list(backup.daily_dir(data).glob("*.zip"))) == 2
    copies = sorted(offsite.glob("*.ssbk"))
    assert [c.name for c in copies] == ["ShopServer_20261013_030000.ssbk",
                                        "ShopServer_20261014_030000.ssbk"]
    plain = tmp_path / "check.zip"
    backup.decrypt_file(copies[-1], plain, PASS)
    assert backup.verify_backup(plain)["rows"]["shopapi.db"] == 5
    assert b"BALE_TOKEN" not in copies[-1].read_bytes()
    (offsite / "someone_else.txt").write_text("keep", encoding="utf-8")
    backup.prune(offsite, ".ssbk", 1)
    assert (offsite / "someone_else.txt").exists()
    status = backup.read_status(data)
    assert status["last_success_at"] == status["at"]


def test_failure_keeps_last_success(data, tmp_path):
    good = backup.run_backup(data, backup.BackupConfig(), now=T0)
    blocker = tmp_path / "file_not_dir"
    blocker.write_text("x", encoding="utf-8")
    bad = backup.run_backup(data, backup.BackupConfig(copy_dir=str(blocker / "sub"), passphrase=PASS),
                            now=T0 + timedelta(days=1))
    assert bad["ok"] is False and bad["last_success_at"] == good["at"]
    assert backup.health(bad, T0 + timedelta(days=1)) is False
    assert backup.health(good, T0 + timedelta(hours=2)) is True
    assert backup.health(good, T0 + timedelta(hours=31)) is False
    assert backup.health({}, T0) is None


def test_is_due():
    cfg = backup.BackupConfig(hour=3)
    at = lambda h, d=12: datetime(2026, 10, d, h, 0, tzinfo=timezone.utc)  # noqa: E731
    assert backup.is_due({}, cfg, at(10))
    assert not backup.is_due({"at": at(3).isoformat()}, cfg, at(10))
    assert not backup.is_due({"at": at(3).isoformat()}, cfg, at(2, 13))
    assert backup.is_due({"at": at(3).isoformat()}, cfg, at(3, 13))
    assert backup.is_due({"at": at(1).isoformat()}, cfg, at(4))      # before today's slot
    assert backup.is_due({"at": at(3, 10).isoformat()}, cfg, at(1, 12))  # missed days
    assert not backup.is_due({}, backup.BackupConfig(enabled=False), at(10))


def test_config_from_values():
    cfg = backup.BackupConfig.from_values({"BACKUP_HOUR": "25", "BACKUP_KEEP_DAYS": "x",
                                           "BACKUP_COPY_DIR": " E:\\Bak ", "BACKUP_ENABLED": "no"})
    # v2.9.4: always the dedicated sub-folder
    assert (cfg.hour, cfg.keep_days, cfg.copy_dir, cfg.enabled) == (
        23, 14, "E:\\Bak\\ShopServerBackup", False)


# ---- restore -----------------------------------------------------------------------
def test_restore_to_replaces_data_and_stale_wal(data, tmp_path):
    zip_path = backup.create_backup(data, tmp_path / "out", now=T0)
    make_db(data / "shopapi.db", 100).close()
    (data / "shopapi.db-wal").write_bytes(b"stale wal")
    (data / "receipts" / "new.jpg").write_bytes(b"after backup")
    backup.restore_to(zip_path, data)
    assert not (data / "shopapi.db-wal").exists()
    assert not (data / "receipts" / "new.jpg").exists()
    conn = sqlite3.connect(data / "shopapi.db")
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 5
    conn.close()
    assert (data / "shoptg" / "session.dpapi").exists()         # never touched


# ---- launcher CLI ----------------------------------------------------------------
def cli(*args: str, env_extra: dict | None = None) -> tuple[int, dict]:
    env = {k: v for k, v in os.environ.items() if k != "SHOPSERVER_BACKUP_PASSPHRASE"}
    env.update(env_extra or {})
    run = subprocess.run([sys.executable, str(LAUNCHER), *args], capture_output=True, text=True,
                         env=env, timeout=120, stdin=subprocess.DEVNULL)
    line = [l for l in run.stdout.splitlines() if l.startswith("{")][-1]
    return run.returncode, json.loads(line)


def test_cli_backup_verify_decrypt_restore(data, tmp_path):
    code, status = cli("--backup-now", "--data-dir", str(data))
    assert code == 0 and status["ok"]
    zip_path = backup.daily_dir(data) / status["file"]
    enc = tmp_path / "copy.ssbk"
    backup.encrypt_file(zip_path, enc, PASS)

    code, out = cli("--verify-backup", str(enc), "--data-dir", str(data))
    assert code == 1 and "passphrase" in out["message"]          # none given, no prompt
    code, out = cli("--verify-backup", str(enc), "--data-dir", str(data),
                    env_extra={"SHOPSERVER_BACKUP_PASSPHRASE": "WRONG-WRONG-WRONG-WRONG"})
    assert code == 1 and "wrong passphrase" in out["message"]
    good = {"SHOPSERVER_BACKUP_PASSPHRASE": PASS}
    code, out = cli("--verify-backup", str(enc), "--data-dir", str(data), env_extra=good)
    assert code == 0 and out["rows"]["shopbots.db"] == 2

    target = tmp_path / "NewServer"
    code, out = cli("--restore-backup", str(enc), "--data-dir", str(target), env_extra=good)
    assert code == 0, out
    assert (target / "receipts" / "order_1.jpg").read_bytes() == b"\xff\xd8receipt"
    code, out = cli("--decrypt-backup", str(enc), "--out", str(tmp_path / "plain.zip"),
                    "--data-dir", str(data), env_extra=good)
    assert code == 0 and (tmp_path / "plain.zip").exists()


def test_new_passphrase_shape():
    phrase = launcher.new_passphrase()
    groups = phrase.split("-")
    assert len(groups) == 8 and all(len(g) == 4 for g in groups)
    assert backup.passphrase_problem(phrase) is None
    assert set(phrase.replace("-", "")) <= set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


def test_insecure_bind():
    assert launcher.insecure_bind("0.0.0.0", tls=False)
    assert not launcher.insecure_bind("0.0.0.0", tls=True)
    assert not launcher.insecure_bind("127.0.0.1", tls=False)


# ---- service grants for the off-server folder ---------------------------------------
def test_local_backup_dir():
    assert winservice.local_backup_dir("") is None
    assert winservice.local_backup_dir(r"\\nas\share\shop") is None
    # v2.9.4: a drive root gets the dedicated sub-folder (granted), never the root
    assert winservice.local_backup_dir("E:\\") == Path(r"E:\ShopServerBackup")
    assert winservice.local_backup_dir("relative\\dir") is None
    assert winservice.local_backup_dir(r"E:\ShopBackup") == Path(r"E:\ShopBackup\ShopServerBackup")
    assert winservice.local_backup_dir(r"E:\ShopServerBackup") == Path(r"E:\ShopServerBackup")


def test_acl_includes_backup_dir(tmp_path):
    commands = winservice.acl_commands(tmp_path, backup_dir=Path(r"E:\ShopBackup"))
    assert ["icacls", r"E:\ShopBackup", "/grant", f"{winservice.SERVICE_ACCOUNT}:(OI)(CI)M",
            "/C", "/Q"] in commands


# ---- logging never shows secrets ------------------------------------------------------
def test_redaction_filter():
    import importlib.util

    source = Path(__file__).resolve().parents[2] / "shopbots" / "app" / "logging_setup.py"
    spec = importlib.util.spec_from_file_location("shopbots_logging_setup", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    redact = module.redact
    token = "1234567890:" + "A" * 35
    text = redact(f"POST https://tapi.bale.ai/bot{token}/sendMessage failed; X-API-Key: abcdefghijkl; "
                  "PWD=hunter2xyz; BACKUP_PASSPHRASE=ABCD-EFGH")
    assert token not in text and "abcdefghijkl" not in text and "hunter2xyz" not in text
    assert "ABCD-EFGH" not in text and "/bot***" in text
