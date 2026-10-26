"""v2.9.2: a backup share on this very computer is written through its local folder."""
from __future__ import annotations

from pathlib import Path

import backup
import localshare
import winservice

NAMES = {"shopsrv", "shopsrv.lan", "192.168.40.100", "localhost", "127.0.0.1"}
SHARES = {"backups": r"G:\Backups", "users": r"C:\Users"}


def test_share_of_this_computer_becomes_its_folder():
    convert = lambda p: localshare.local_path_for(p, names=NAMES, shares=SHARES)  # noqa: E731
    assert convert(r"\\SHOPSRV\Backups\Shop") == r"G:\Backups\Shop"
    assert convert(r"\\shopsrv.lan\backups") == r"G:\Backups"
    assert convert("//192.168.40.100/Backups/a/b") == r"G:\Backups\a\b"
    assert convert(r"\\localhost\D$\Shop") == r"D:\Shop"           # administrative share
    # another computer, an unknown share, a local folder: unchanged (None)
    assert convert(r"\\NAS\Backups") is None
    assert convert(r"\\SHOPSRV\Nope") is None
    assert convert(r"D:\Backups") is None
    assert convert("") is None


def test_service_grants_and_writes_the_local_folder(monkeypatch):
    monkeypatch.setattr(localshare, "this_computer_names", lambda: NAMES)
    monkeypatch.setattr(localshare, "share_folders", lambda: SHARES)
    assert winservice.local_backup_dir(r"\\SHOPSRV\Backups\Shop") == \
        Path(r"G:\Backups\Shop\ShopServerBackup")
    assert winservice.local_backup_dir(r"\\NAS\Backups") is None
    config = backup.BackupConfig.from_values({"BACKUP_COPY_DIR": r"\\shopsrv\Backups\Shop"})
    assert config.copy_dir == r"G:\Backups\Shop\ShopServerBackup"
    config = backup.BackupConfig.from_values({"BACKUP_COPY_DIR": r"\\NAS\Backups"})
    assert config.copy_dir == r"\\NAS\Backups\ShopServerBackup"


def test_v294_drive_root_share_is_never_written_directly(monkeypatch):
    """2.9.3: \\\\192.168.20.150\\E (this PC's share of the whole E: drive) became
    E:\\ and the service had no grant there -> "PermissionError: Access is denied".
    Now: E:\\ShopServerBackup, created and granted to the service account."""
    monkeypatch.setattr(localshare, "this_computer_names", lambda: {"192.168.20.150"})
    monkeypatch.setattr(localshare, "share_folders", lambda: {"e": "E:\\"})
    raw = r"\\192.168.20.150\E"
    assert backup.BackupConfig.from_values({"BACKUP_COPY_DIR": raw}).copy_dir == \
        r"E:\ShopServerBackup"
    target = winservice.local_backup_dir(raw)
    assert target == Path(r"E:\ShopServerBackup")
    commands = winservice.acl_commands(Path(r"C:\Data"), backup_dir=target)
    assert ["icacls", r"E:\ShopServerBackup", "/grant",
            f"{winservice.SERVICE_ACCOUNT}:(OI)(CI)M", "/C", "/Q"] in commands
