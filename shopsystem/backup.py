"""Daily backup of the shop server's data folder (REQUIREMENTS §10).

What is backed up
    ``.env``, ``shopapi.db``, ``shopbots.db`` (consistent snapshots through
    SQLite's online-backup API, safe while the server writes), the bot texts
    ``messages.fa.json`` and the folders ``receipts``, ``pricelists``, ``tls``.
    **Never** the Telegram worker session (``shoptg\\``): it is encrypted with
    DPAPI LocalMachine and only opens on this computer; after a restore on new
    hardware the shop's Telegram account logs in again.

Where
    1. ``<data>\\backups\\daily\\ShopServer_<yyyyMMdd_HHmmss>.zip`` - complete,
       plain zip; protected by the data folder's ACL. ``BACKUP_KEEP_DAYS`` (14)
       are kept.
    2. Off-server copy in ``BACKUP_COPY_DIR`` (USB disk, second disk, share):
       ``ShopServer_<...>.ssbk`` = the same zip encrypted with AES-256-GCM, key
       from ``BACKUP_PASSPHRASE`` (scrypt). Without a passphrase nothing is
       copied: a plain copy would carry the SQL password and the Bale token.

Restore test
    Every backup is checked right after it is written: manifest SHA-256 of
    each file, ``PRAGMA integrity_check`` and row counts of both databases on
    an extracted copy. The off-server copy is read back, decrypted and its
    SHA-256 compared with the local zip. The result goes to
    ``<data>\\backups\\status.json``, which shopapi's health monitor turns into
    a Bale alert + ShopAdmin warning when a backup fails or is overdue.

Encrypted file format (``.ssbk``)
    header = b"SHOPBAK1" | log2(n) r p (1 byte each) | salt (16) |
             nonce prefix (7) | chunk size (4, big endian)
    then the zip in chunks of ``chunk size`` bytes, each sealed with
    AES-256-GCM: nonce = prefix | chunk index (4, BE) | last-chunk flag (1),
    associated data = header. A missing last chunk, a reordered or edited
    chunk or a wrong passphrase all fail authentication.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import struct
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional

FILES = (".env", "messages.fa.json")
DATABASES = ("shopapi.db", "shopbots.db")
FOLDERS = ("receipts", "pricelists", "tls")
MANIFEST = "manifest.json"
PREFIX = "ShopServer_"
STATUS_FILE = "status.json"

MAGIC = b"SHOPBAK1"
CHUNK = 1 << 20
SCRYPT_LOG_N, SCRYPT_R, SCRYPT_P = 15, 8, 1
HEADER = struct.Struct(">8sBBB16s7sI")
TAG = 16
MIN_PASSPHRASE = 20

DEFAULT_HOUR = 3
DEFAULT_KEEP_DAYS = 14
#: The health monitor reports the backup as down when the last good one is older.
OVERDUE_HOURS = 30


class BackupError(Exception):
    """A backup, verification or decryption that must be reported as failed."""


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def backups_root(data_dir: Path) -> Path:
    return Path(data_dir) / "backups"


def daily_dir(data_dir: Path) -> Path:
    return backups_root(data_dir) / "daily"


def status_path(data_dir: Path) -> Path:
    return backups_root(data_dir) / STATUS_FILE


def _snapshot_db(source: Path, target: Path) -> dict[str, int]:
    """Consistent copy of a live SQLite database; returns its table row counts."""
    src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
            return _table_counts(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    names = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    # table names come from sqlite_master of our own file, quoted as identifiers
    return {name: int(conn.execute(f'SELECT COUNT(*) FROM "{name.replace(chr(34), "")}"').fetchone()[0])
            for name in names}


# --------------------------------------------------------------------------
# create / verify
# --------------------------------------------------------------------------
def create_backup(data_dir: Path, target_dir: Path, *, now: Optional[datetime] = None) -> Path:
    """Write one complete zip of the data folder into ``target_dir``."""
    data_dir = Path(data_dir)
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or _now()).strftime("%Y%m%d_%H%M%S")
    final = target_dir / f"{PREFIX}{stamp}.zip"
    partial = final.with_suffix(".zip.partial")
    manifest: dict = {"format": 1, "created": (now or _now()).isoformat(timespec="seconds"),
                      "files": {}, "databases": {}}
    with tempfile.TemporaryDirectory(prefix="shopbak_") as tmp:
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            def add(path: Path, name: str) -> None:
                archive.write(path, name)
                manifest["files"][name] = {"sha256": _sha256(path), "size": path.stat().st_size}

            for name in DATABASES:
                source = data_dir / name
                if source.exists():
                    snap = Path(tmp) / name
                    manifest["databases"][name] = _snapshot_db(source, snap)
                    add(snap, name)
            for name in FILES:
                source = data_dir / name
                if source.is_file():
                    add(source, name)
            for folder in FOLDERS:
                root = data_dir / folder
                if not root.is_dir():
                    continue
                for path in sorted(root.rglob("*")):
                    if path.is_file():
                        add(path, path.relative_to(data_dir).as_posix())
            archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=1))
    os.replace(partial, final)
    return final


def verify_backup(zip_path: Path) -> dict:
    """The restore test: every file intact, both databases open and consistent."""
    zip_path = Path(zip_path)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            manifest = json.loads(archive.read(MANIFEST).decode("utf-8"))
            names = set(archive.namelist()) - {MANIFEST}
            expected = set(manifest.get("files", {}))
            if names != expected:
                raise BackupError("the file list does not match the manifest")
            with tempfile.TemporaryDirectory(prefix="shopbak_verify_") as tmp:
                for name, info in manifest["files"].items():
                    if name.startswith("/") or ".." in Path(name).parts:
                        raise BackupError(f"unsafe path in backup: {name}")
                    digest = hashlib.sha256()
                    with archive.open(name) as handle:
                        for block in iter(lambda: handle.read(CHUNK), b""):
                            digest.update(block)
                    if digest.hexdigest() != info.get("sha256"):
                        raise BackupError(f"damaged file in backup: {name}")
                tables: dict[str, dict[str, int]] = {}
                for name, counts in manifest.get("databases", {}).items():
                    path = Path(archive.extract(name, tmp))
                    conn = sqlite3.connect(path)
                    try:
                        check = conn.execute("PRAGMA integrity_check").fetchone()[0]
                        if check != "ok":
                            raise BackupError(f"{name}: integrity check failed")
                        tables[name] = _table_counts(conn)
                    finally:
                        conn.close()
                    if tables[name] != counts:
                        raise BackupError(f"{name}: row counts differ from the manifest")
    except (zipfile.BadZipFile, KeyError, ValueError, sqlite3.DatabaseError, OSError) as exc:
        raise BackupError(f"unreadable backup ({type(exc).__name__})") from exc
    return {"ok": True, "files": len(manifest["files"]),
            "rows": {db: sum(c.values()) for db, c in tables.items()},
            "created": manifest.get("created")}


# --------------------------------------------------------------------------
# encryption (off-server copy)
# --------------------------------------------------------------------------
def normalise_passphrase(passphrase: str) -> bytes:
    """Spaces and hyphens do not count (easier to copy from paper); case does."""
    text = unicodedata.normalize("NFC", passphrase or "")
    return "".join(ch for ch in text if not ch.isspace() and ch != "-").encode("utf-8")


def passphrase_problem(passphrase: str) -> Optional[str]:
    if len(normalise_passphrase(passphrase)) < MIN_PASSPHRASE:
        return f"the backup passphrase must have at least {MIN_PASSPHRASE} characters"
    return None


def _derive_key(passphrase: str, salt: bytes, log_n: int, r: int, p: int) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    return Scrypt(salt=salt, length=32, n=1 << log_n, r=r, p=p).derive(normalise_passphrase(passphrase))


def _nonce(prefix: bytes, index: int, last: bool) -> bytes:
    return prefix + struct.pack(">I", index) + (b"\x01" if last else b"\x00")


def encrypt_file(source: Path, target: Path, passphrase: str) -> None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    problem = passphrase_problem(passphrase)
    if problem:
        raise BackupError(problem)
    salt, prefix = os.urandom(16), os.urandom(7)
    header = HEADER.pack(MAGIC, SCRYPT_LOG_N, SCRYPT_R, SCRYPT_P, salt, prefix, CHUNK)
    aead = AESGCM(_derive_key(passphrase, salt, SCRYPT_LOG_N, SCRYPT_R, SCRYPT_P))
    with Path(source).open("rb") as src, Path(target).open("wb") as dst:
        dst.write(header)
        index = 0
        current = src.read(CHUNK)
        while True:
            following = src.read(CHUNK)
            last = not following
            dst.write(aead.encrypt(_nonce(prefix, index, last), current, header))
            if last:
                break
            current, index = following, index + 1
            if index >= 0xFFFFFFFF:
                raise BackupError("backup too large")


def decrypt_file(source: Path, target: Path, passphrase: str) -> None:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    with Path(source).open("rb") as src:
        header = src.read(HEADER.size)
        if len(header) != HEADER.size:
            raise BackupError("not a shop backup file")
        magic, log_n, r, p, salt, prefix, chunk = HEADER.unpack(header)
        if magic != MAGIC or not (10 <= log_n <= 20) or chunk <= 0 or chunk > 64 * CHUNK:
            raise BackupError("not a shop backup file")
        aead = AESGCM(_derive_key(passphrase, salt, log_n, r, p))
        size = chunk + TAG
        partial = Path(str(target) + ".partial")
        try:
            with partial.open("wb") as dst:
                index = 0
                current = src.read(size)
                while True:
                    following = src.read(size)
                    last = not following
                    try:
                        dst.write(aead.decrypt(_nonce(prefix, index, last), current, header))
                    except InvalidTag:
                        raise BackupError("wrong passphrase, or the file is damaged or incomplete") from None
                    if last:
                        break
                    current, index = following, index + 1
            os.replace(partial, target)
        finally:
            if partial.exists():
                partial.unlink()


def copy_offsite(zip_path: Path, copy_dir: Path, passphrase: str) -> Path:
    """Encrypt the zip into ``copy_dir`` and prove the copy decrypts to the same bytes."""
    copy_dir = Path(copy_dir)
    copy_dir.mkdir(parents=True, exist_ok=True)
    final = copy_dir / (Path(zip_path).stem + ".ssbk")
    partial = Path(str(final) + ".partial")
    try:
        encrypt_file(zip_path, partial, passphrase)
        os.replace(partial, final)
    finally:
        if partial.exists():
            partial.unlink()
    with tempfile.TemporaryDirectory(prefix="shopbak_offsite_") as tmp:
        plain = Path(tmp) / "check.zip"
        decrypt_file(final, plain, passphrase)
        if _sha256(plain) != _sha256(Path(zip_path)):
            raise BackupError("the off-server copy does not match the local backup")
    return final


def prune(folder: Path, suffix: str, keep: int) -> list[Path]:
    """Delete our own older backups beyond ``keep`` (never any other file)."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    ours = sorted(p for p in folder.glob(f"{PREFIX}*{suffix}") if p.is_file())
    removed = ours[:-keep] if keep > 0 else []
    for path in removed:
        try:
            path.unlink()
        except OSError:
            pass
    return removed


# --------------------------------------------------------------------------
# the daily job
# --------------------------------------------------------------------------
def offsite_dir(raw: Optional[str]) -> str:
    """``BACKUP_COPY_DIR``; v2.9.2: a share of this very computer is written through
    its local folder (the service account is refused on its own share)."""
    text = str(raw or "").strip()
    try:
        from localshare import local_path_for
        return local_path_for(text) or text
    except Exception:  # noqa: BLE001 - never stop the backup over the lookup
        return text


@dataclass
class BackupConfig:
    hour: int = DEFAULT_HOUR
    keep_days: int = DEFAULT_KEEP_DAYS
    copy_dir: str = ""
    passphrase: str = ""
    enabled: bool = True

    @classmethod
    def from_values(cls, values: Mapping[str, str]) -> "BackupConfig":
        def number(key: str, default: int, lo: int, hi: int) -> int:
            try:
                return min(hi, max(lo, int(str(values.get(key, default)).strip())))
            except ValueError:
                return default

        enabled = str(values.get("BACKUP_ENABLED", "true")).strip().lower() not in {"0", "false", "no", "off"}
        return cls(hour=number("BACKUP_HOUR", DEFAULT_HOUR, 0, 23),
                   keep_days=number("BACKUP_KEEP_DAYS", DEFAULT_KEEP_DAYS, 1, 365),
                   copy_dir=offsite_dir(values.get("BACKUP_COPY_DIR")),
                   passphrase=str(values.get("BACKUP_PASSPHRASE", "") or ""),
                   enabled=enabled)


def read_status(data_dir: Path) -> dict:
    try:
        return json.loads(status_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_status(data_dir: Path, status: dict) -> None:
    path = status_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def run_backup(data_dir: Path, config: BackupConfig, *, now: Optional[datetime] = None) -> dict:
    """Back up, verify, copy off-server, prune; write and return the status.

    Never raises: every failure is written to the status (and so alerted).
    """
    data_dir = Path(data_dir)
    now = now or _now()
    previous = read_status(data_dir)
    status: dict = {"at": now.isoformat(timespec="seconds"), "ok": False, "error": None,
                    "file": None, "size": None, "verify": None,
                    "offsite": {"configured": bool(config.copy_dir), "ok": None,
                                "file": None, "error": None},
                    "last_success_at": previous.get("last_success_at")}
    try:
        zip_path = create_backup(data_dir, daily_dir(data_dir), now=now)
        status["file"], status["size"] = zip_path.name, zip_path.stat().st_size
        status["verify"] = verify_backup(zip_path)
        prune(daily_dir(data_dir), ".zip", config.keep_days)
        ok = True
        if config.copy_dir:
            try:
                if not config.passphrase:
                    raise BackupError("BACKUP_PASSPHRASE is not set - the off-server copy "
                                      "is never written unencrypted")
                copy = copy_offsite(zip_path, Path(config.copy_dir), config.passphrase)
                prune(Path(config.copy_dir), ".ssbk", config.keep_days)
                status["offsite"].update(ok=True, file=copy.name)
            except (BackupError, OSError) as exc:
                ok = False
                status["offsite"].update(ok=False, error=_describe(exc))
        status["ok"] = ok
        if not ok:
            status["error"] = "off-server copy failed"
    except (BackupError, OSError, sqlite3.Error) as exc:
        status["error"] = _describe(exc)
    if status["ok"]:
        status["last_success_at"] = status["at"]
    _write_status(data_dir, status)
    return status


def _describe(exc: Exception) -> str:
    """Error text without paths' contents or secrets (only our own messages)."""
    if isinstance(exc, BackupError):
        return str(exc)[:300]
    if isinstance(exc, OSError):
        return f"{type(exc).__name__}: {exc.strerror or ''}".strip()[:300]
    return type(exc).__name__


def is_due(status: Mapping, config: BackupConfig, now: datetime) -> bool:
    """Once a day at ``config.hour`` local time; at once when the last attempt
    is older than a day (e.g. the server was off at that hour)."""
    if not config.enabled:
        return False
    last = _parse(status.get("at"))
    if last is None:
        return True
    if now - last >= timedelta(hours=24):
        return True
    today_slot = now.replace(hour=config.hour, minute=0, second=0, microsecond=0)
    return now >= today_slot and last < today_slot


def _parse(raw) -> Optional[datetime]:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def health(status: Mapping, now: datetime, *, overdue_hours: int = OVERDUE_HOURS) -> Optional[bool]:
    """For the health monitor: None = backups never ran, False = failing or overdue."""
    if not status:
        return None
    if not status.get("ok"):
        return False
    last = _parse(status.get("last_success_at"))
    return last is not None and now - last < timedelta(hours=overdue_hours)


def scheduler_loop(data_dir: Path, read_values: Callable[[], Mapping[str, str]], stop, *,
                   log=None, check_every: float = 60.0, first_delay: float = 600.0) -> None:
    """Supervisor thread: run the daily backup when due until ``stop`` is set.

    The first check waits ``first_delay`` seconds so the server is up first.
    """
    if stop.wait(first_delay):
        return
    while True:
        try:
            config = BackupConfig.from_values(read_values())
            if is_due(read_status(data_dir), config, _now()):
                status = run_backup(data_dir, config)
                if log is not None:
                    if status["ok"]:
                        log.info("daily backup OK: %s", status["file"])
                    else:
                        log.error("daily backup FAILED: %s", status["error"] or status["offsite"]["error"])
        except Exception as exc:  # noqa: BLE001 - the supervisor must keep running
            if log is not None:
                log.error("backup scheduler error (%s)", type(exc).__name__)
        if stop.wait(check_every):
            return


def restore_to(zip_path: Path, data_dir: Path) -> None:
    """Extract a verified backup over ``data_dir`` (the service must be stopped).

    Used by tests and by ``--restore-backup``; restore.ps1 does the same with
    a safety copy and a health check around it.
    """
    verify_backup(zip_path)
    data_dir = Path(data_dir)
    with zipfile.ZipFile(zip_path) as archive:
        names = [n for n in archive.namelist() if n != MANIFEST]
        for folder in FOLDERS:
            live = data_dir / folder
            if live.exists():
                shutil.rmtree(live)
        for name in FILES + DATABASES:
            live = data_dir / name
            if live.exists() and name not in names:
                live.unlink()
        for name in DATABASES:
            # a WAL/journal left by the old database would corrupt the restored one
            for suffix in ("-wal", "-shm", "-journal"):
                stale = data_dir / (name + suffix)
                if stale.exists():
                    stale.unlink()
        for name in names:
            archive.extract(name, data_dir)
