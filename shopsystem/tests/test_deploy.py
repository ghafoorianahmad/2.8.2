"""update.ps1 / install.ps1 helpers, run for real in PowerShell against a fake
service (``SHOP_DEPLOY_FAKE``): no service, firewall or ACL is touched."""
from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")

pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell not available")


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_program(folder: Path, version: str, health: str = "ok", start_hook: str = "") -> Path:
    write(folder / "ShopSystem.exe", "not a real exe")
    write(folder / "version.txt", version)
    write(folder / "fake_health.txt", health)
    if start_hook:
        write(folder / "fake_start.ps1", start_hook)
    return folder


@pytest.fixture
def site(tmp_path):
    install = make_program(tmp_path / "Program Files" / "ShopServer" / "ShopSystem", "old")
    data = tmp_path / "ProgramData" / "ShopServer"
    write(data / ".env", "API_PORT=8443\n")
    write(data / "shopapi.db", "old-db")
    write(data / "receipts" / "order1.jpg", "receipt")
    fake = tmp_path / "fake"
    write(fake / "pathname.txt", f'"{install / "ShopSystem.exe"}" --winservice --data-dir "{data}"')
    return {"install": install, "data": data, "fake": fake, "tmp": tmp_path}


def package(tmp_path: Path, version: str, **kwargs) -> Path:
    root = tmp_path / f"pkg_{version}"
    make_program(root / "ShopSystem", version, **kwargs)
    write(root / "VERSION.txt", version)
    return root


def run(script: str, fake: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, SHOP_DEPLOY_FAKE=str(fake))
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(DEPLOY / script), *args],
        capture_output=True, text=True, env=env, timeout=120,
    )


def calls(fake: Path) -> list[str]:
    path = fake / "calls.txt"
    return path.read_text(encoding="utf-8").split() if path.exists() else []


def backups(data: Path) -> list[Path]:
    root = data / "backups"
    return sorted(root.glob("update_*")) if root.exists() else []


def test_update_ok(site):
    pkg = package(site["tmp"], "new")
    result = run("update.ps1", site["fake"], "-Package", str(pkg), "-HealthTimeout", "1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (site["install"] / "version.txt").read_text(encoding="utf-8") == "new"
    assert calls(site["fake"]) == ["stop", "start"]
    [backup] = backups(site["data"])
    assert (backup / "program" / "version.txt").read_text(encoding="utf-8") == "old"
    assert (backup / "data" / "shopapi.db").read_text(encoding="utf-8") == "old-db"
    assert (backup / "data" / "receipts" / "order1.jpg").exists()
    assert not Path(str(site["install"]) + ".new").exists()
    assert "UPDATE OK" in (site["data"] / "update.log").read_text(encoding="utf-8")


def test_update_unhealthy_rolls_back_program_and_data(site):
    # the new version "migrates" the database and adds a file, then never gets healthy
    hook = ("param($d)\nSet-Content -LiteralPath (Join-Path $d 'shopapi.db') -Value 'migrated'\n"
            "Set-Content -LiteralPath (Join-Path $d 'receipts\\new.jpg') -Value 'x'\n")
    pkg = package(site["tmp"], "bad", health="fail", start_hook=hook)
    result = run("update.ps1", site["fake"], "-Package", str(pkg), "-HealthTimeout", "1")
    assert result.returncode == 3, result.stdout + result.stderr
    assert (site["install"] / "version.txt").read_text(encoding="utf-8") == "old"
    assert (site["data"] / "shopapi.db").read_text(encoding="utf-8") == "old-db"
    assert not (site["data"] / "receipts" / "new.jpg").exists()
    assert (site["data"] / "receipts" / "order1.jpg").exists()
    [backup] = backups(site["data"])
    assert (backup / "failed_program" / "version.txt").read_text(encoding="utf-8") == "bad"
    assert calls(site["fake"]) == ["stop", "start", "stop", "start"]
    assert "ROLLED BACK" in (site["data"] / "update.log").read_text(encoding="utf-8")


def test_rollback_reports_when_old_version_also_unhealthy(site):
    (site["install"] / "fake_health.txt").write_text("fail", encoding="utf-8")
    pkg = package(site["tmp"], "bad", health="fail")
    result = run("update.ps1", site["fake"], "-Package", str(pkg), "-HealthTimeout", "1")
    assert result.returncode == 4
    assert (site["install"] / "version.txt").read_text(encoding="utf-8") == "old"


def test_update_from_zip_and_keeps_three_backups(site):
    for n in range(4):
        pkg = package(site["tmp"], f"v{n}")
        archive = site["tmp"] / f"v{n}.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for file in pkg.rglob("*"):
                zf.write(file, file.relative_to(pkg).as_posix())
        result = run("update.ps1", site["fake"], "-Package", str(archive), "-HealthTimeout", "1")
        assert result.returncode == 0, result.stdout + result.stderr
    assert (site["install"] / "version.txt").read_text(encoding="utf-8") == "v3"
    kept = backups(site["data"])
    assert len(kept) == 3
    assert (kept[-1] / "program" / "version.txt").read_text(encoding="utf-8") == "v2"


def test_update_without_service_changes_nothing(site):
    (site["fake"] / "pathname.txt").unlink()
    result = run("update.ps1", site["fake"], "-Package", str(package(site["tmp"], "new")))
    assert result.returncode == 1
    assert (site["install"] / "version.txt").read_text(encoding="utf-8") == "old"
    assert calls(site["fake"]) == []


def test_update_rejects_package_without_exe(site, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = run("update.ps1", site["fake"], "-Package", str(empty))
    assert result.returncode == 1 and calls(site["fake"]) == []


def _ps(fake: Path, body: str) -> subprocess.CompletedProcess:
    script = f". '{DEPLOY / 'common.ps1'}'\n{body}"
    env = dict(os.environ, SHOP_DEPLOY_FAKE=str(fake))
    return subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                          capture_output=True, text=True, env=env, timeout=60)


def test_firewall_defaults_to_local_subnet_and_accepts_a_list(tmp_path):
    fake = tmp_path / "fake"
    fake.mkdir()
    assert _ps(fake, "Set-ShopFirewall 'x.exe' 8443 ''").returncode == 0
    assert (fake / "firewall.txt").read_text(encoding="utf-8").strip() == "8443 localsubnet"
    assert _ps(fake, "Set-ShopFirewall 'x.exe' 8443 '192.168.10.0/24; 192.168.10.5'").returncode == 0
    assert (fake / "firewall.txt").read_text(encoding="utf-8").strip() == "8443 192.168.10.0/24,192.168.10.5"
    bad = _ps(fake, "Set-ShopFirewall 'x.exe' 8443 'any'")
    assert bad.returncode != 0 or "Not an IP" in bad.stdout + bad.stderr


def test_split_service_path_variants(tmp_path):
    out = _ps(tmp_path, "$a = Split-ServicePath '\"C:\\Program Files\\S\\ShopSystem.exe\" --winservice "
                        "--data-dir \"D:\\Shop Data\"'; \"$($a.InstallDir)|$($a.DataDir)\"")
    assert out.stdout.strip() == r"C:\Program Files\S|D:\Shop Data"
