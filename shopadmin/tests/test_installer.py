"""Tests for the installer definition (Issue 3).

The Inno Setup script is parsed as text: these tests pin down the parts of the
installer the shop owner depends on (shortcut names, install location, uninstall
entry, both privilege modes) without needing Inno Setup installed.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALLER_DIR = ROOT / "installer"
ISS_PATH = INSTALLER_DIR / "ShopAdmin.iss"
BAT_PATH = ROOT / "build_installer.bat"
INSTALLER_README = INSTALLER_DIR / "installer_readme.txt"

REQUIRED_SECTIONS = ("[Setup]", "[Files]", "[Icons]", "[Run]", "[Tasks]", "[UninstallDelete]")


def preprocess(text: str, defines: set[str]) -> str:
    """Resolve the script's #ifdef / #ifndef / #else / #endif blocks.

    One script builds both installers; each is tested as Inno Setup's
    preprocessor would see it.
    """
    out: list[str] = []
    stack: list[bool] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#ifdef "):
            stack.append(stripped.split()[1] in defines)
            continue
        if stripped.startswith("#ifndef "):
            stack.append(stripped.split()[1] not in defines)
            continue
        if stripped.startswith("#else"):
            stack[-1] = not stack[-1]
            continue
        if stripped.startswith("#endif"):
            stack.pop()
            continue
        if stripped.startswith("#if "):
            stack.append(False)  # build-time checks: not part of the script body
            continue
        if stripped.startswith("#error"):
            continue
        if all(stack):
            out.append(line)
    assert not stack, "unbalanced #if blocks"
    return "\n".join(out)


@pytest.fixture(scope="module")
def raw_iss() -> str:
    assert ISS_PATH.is_file(), f"missing {ISS_PATH}"
    return ISS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def iss_text(raw_iss) -> str:
    """The staff-computer installer (ShopAdminSetup.exe)."""
    return preprocess(raw_iss, set())


@pytest.fixture(scope="module")
def server_iss(raw_iss) -> str:
    """The server-computer installer (ShopServerSetup.exe)."""
    return preprocess(raw_iss, {"SERVER"})


@pytest.fixture(scope="module")
def bat_text() -> str:
    assert BAT_PATH.is_file(), f"missing {BAT_PATH}"
    return BAT_PATH.read_text(encoding="utf-8", errors="replace")


def _section(text: str, name: str) -> str:
    """Return the body of one [Section], with ``\\`` line continuations joined."""
    pattern = re.compile(
        r"^\s*" + re.escape(name) + r"\s*$(.*?)(?=^\s*\[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    assert match, f"section {name} not found"
    return _join_continuations(match.group(1))


def _join_continuations(body: str) -> str:
    """Inno Setup uses a trailing backslash to continue a directive.

    Joining them first means a directive can be inspected as one line, which is
    what makes assertions like "this shortcut belongs to that task" reliable.
    """
    body = re.sub(r"\\\s*\r?\n\s*", " ", body)
    return re.sub(r"\\\s*\r?\n\s*", " ", body)


def _lines(body: str) -> list[str]:
    return [line.strip() for line in body.splitlines() if line.strip()]


def _directives(text: str, name: str) -> list[str]:
    """Return the values of a key inside a section body."""
    return [
        match.group(1).strip()
        for match in re.finditer(r"^\s*" + re.escape(name) + r"\s*=\s*(.+?)\s*$",
                                 text, re.MULTILINE)
    ]


# --------------------------------------------------------------------------
# files exist
# --------------------------------------------------------------------------
def test_installer_files_exist():
    assert ISS_PATH.is_file(), "installer/ShopAdmin.iss is missing"
    assert BAT_PATH.is_file(), "build_installer.bat is missing"
    assert INSTALLER_README.is_file(), "installer/installer_readme.txt is missing"


# --------------------------------------------------------------------------
# .iss structure
# --------------------------------------------------------------------------
@pytest.mark.parametrize("section", REQUIRED_SECTIONS)
def test_iss_has_the_required_sections(iss_text, section):
    assert re.search(r"^\s*" + re.escape(section) + r"\s*$", iss_text, re.MULTILINE), (
        f"{section} is required"
    )


def test_iss_defines_the_output_installer_name(iss_text):
    setup = _section(iss_text, "[Setup]")
    assert _directives(setup, "OutputBaseFilename") == ["ShopAdminSetup"], (
        "the installer must be called ShopAdminSetup.exe"
    )
    assert _directives(setup, "OutputDir"), "OutputDir must be set"


def test_iss_installs_under_program_files_when_all_users(iss_text):
    setup = _section(iss_text, "[Setup]")
    directory = _directives(setup, "DefaultDirName")[0]
    assert "{autopf}" in directory, f"expected an auto Program Files path, got {directory}"
    assert "MyAppName" in directory, f"expected the app name in the path, got {directory}"


def test_the_app_name_define_is_ShopAdmin(iss_text):
    """DefaultDirName resolves {#MyAppName}, so pin the define itself."""
    match = re.search(r'#define\s+MyAppName\s+"([^"]+)"', iss_text)
    assert match, "MyAppName must be defined"
    assert match.group(1) == "ShopAdmin"
    match_fa = re.search(r'#define\s+MyAppNameFa\s+"([^"]+)"', iss_text)
    assert match_fa and match_fa.group(1) == "مدیریت فروشگاه"


def test_iss_defaults_to_per_user_and_allows_per_machine(iss_text):
    setup = _section(iss_text, "[Setup]")
    assert _directives(setup, "PrivilegesRequired") == ["lowest"], (
        "per-user install (no admin rights) must be the default"
    )
    overrides = _directives(setup, "PrivilegesRequiredOverridesAllowed")
    assert overrides and "dialog" in overrides[0], (
        "the user must be offered the per-machine choice as well"
    )


def test_iss_creates_the_persian_desktop_shortcut(iss_text):
    icons = _section(iss_text, "[Icons]")
    desktop_lines = [line for line in _lines(icons) if "{autodesktop}" in line]
    assert desktop_lines, "a Desktop shortcut is required"
    assert any("MyAppNameFa" in line for line in desktop_lines), (
        "the shortcut must use the Persian name مدیریت فروشگاه"
    )
    assert any("desktopicon" in line for line in desktop_lines), (
        "the Desktop shortcut must belong to the optional desktopicon task"
    )


def test_iss_creates_the_persian_start_menu_entry(iss_text):
    icons = _section(iss_text, "[Icons]")
    start_lines = [line for line in _lines(icons) if "{group}" in line]
    assert start_lines, "a Start Menu entry is required"
    assert any("MyAppNameFa" in line for line in start_lines), (
        "the Start Menu entry must use the Persian name"
    )


def test_iss_registers_an_uninstaller(iss_text):
    setup = _section(iss_text, "[Setup]")
    assert _directives(setup, "UninstallDisplayName"), "uninstall entry name is required"
    assert _directives(setup, "UninstallDisplayIcon"), "uninstall icon is required"
    icons = _section(iss_text, "[Icons]")
    assert "{uninstallexe}" in icons, "a Start Menu uninstall shortcut is expected"


def test_iss_ships_both_applications(server_iss):
    files = _section(server_iss, "[Files]")
    assert "STAGING_DIR" in files, "the staging directory must be the source"
    assert re.search(r"ShopAdmin\\\*", files), "the ShopAdmin build must be included"
    assert re.search(r"ShopSystem\\\*", files), "the ShopSystem service must be included"
    # The service goes into its own sub-folder next to the app.
    assert "{app}\\ShopSystem" in files


def test_iss_opens_the_readme_after_install(iss_text):
    run = _section(iss_text, "[Run]")
    assert "installer_readme.txt" in run, "the 'read me first' option must open the readme"
    assert "postinstall" in run
    tasks = _section(iss_text, "[Tasks]")
    assert "readme" in tasks, "the readme must be an optional task (checkbox)"


def test_iss_can_launch_the_app_after_install(iss_text):
    run = _section(iss_text, "[Run]")
    assert "MyAppExeName" in run
    assert "launchapp" in _section(iss_text, "[Tasks]")


def test_iss_does_not_delete_user_data_on_uninstall(iss_text):
    """The uninstaller must never remove the local database, logs or settings."""
    body = _section(iss_text, "[UninstallDelete]")
    # Only the VALUE side of each directive matters: the section carries a
    # comment explaining that user data is deliberately kept, and that comment
    # must not be mistaken for a deletion rule.
    values = " ".join(
        line.split(":", 1)[1] if ":" in line else ""
        for line in _lines(body) if not line.startswith(";")
    ).lower()
    for forbidden in ("shopadmin.db", "app.log", "localappdata", "{userappdata}",
                      "shopapi.db", "shopadmin"):
        assert forbidden not in values, (
            f"the uninstaller must not delete {forbidden}"
        )
    # It should still tidy up the service log inside the install folder.
    assert "shopapi.log" in values, (
        "the service log next to the app should be cleaned up"
    )


def test_iss_forces_a_64_bit_install(iss_text):
    setup = _section(iss_text, "[Setup]")
    assert _directives(setup, "ArchitecturesInstallIn64BitMode"), (
        "a 64-bit install mode is required for the Qt runtime"
    )


def test_iss_uses_compression_and_a_stable_app_id(iss_text):
    setup = _section(iss_text, "[Setup]")
    assert _directives(setup, "Compression"), "compression keeps the download small"
    app_id = _directives(setup, "AppId")[0]
    assert app_id.startswith("{{"), "AppId must be a braced GUID"
    assert len(app_id) > 30, "AppId must be a real GUID so upgrades stay in place"


def test_iss_custom_messages_are_persian(iss_text):
    """Every task label the user reads must be Persian."""
    messages = _section(iss_text, "[CustomMessages]")
    persian = re.compile(r"[\u0600-\u06FF]")
    labels = [line for line in messages.splitlines() if line.strip().startswith("english.")]
    assert len(labels) >= 4, "expected several user-visible task labels"
    for line in labels:
        assert persian.search(line), f"this task label is not Persian: {line.strip()}"


# --------------------------------------------------------------------------
# build_installer.bat
# --------------------------------------------------------------------------
def test_bat_runs_pyinstaller_first(bat_text):
    assert "build_shopadmin.py" in bat_text, (
        "the installer build must run the existing PyInstaller build first"
    )


def test_bat_stages_both_applications(bat_text):
    assert "installer_staging" in bat_text, "a staging folder is required"
    assert "staging" in bat_text.lower()
    assert re.search(r"shopsystem\\dist\\ShopSystem", bat_text, re.IGNORECASE), (
        "the ShopSystem build must be staged too"
    )


def test_bat_calls_iscc_with_the_iss_script(bat_text):
    assert "ISCC" in bat_text, "Inno Setup's compiler must be invoked"
    assert "ShopAdmin.iss" in bat_text, "the .iss script must be passed to iscc"
    assert "DSTAGING_DIR" in bat_text, "the staging path must be passed to the script"


def test_bat_leaves_the_installer_in_dist_installer(bat_text):
    assert re.search(r"dist\\installer", bat_text), (
        "ShopAdminSetup.exe must end up in dist\\installer"
    )


def test_bat_locates_inno_setup_in_the_usual_places(bat_text):
    """The build machine may have Inno Setup in Program Files or per-user."""
    assert "Inno Setup 6" in bat_text
    assert "LOCALAPPDATA" in bat_text or "ProgramFiles" in bat_text
    assert "INNO_SETUP_ISCC" in bat_text, "an override for a custom install path is expected"


def test_bat_reports_a_clear_message_when_inno_setup_is_missing(bat_text):
    """A missing compiler must be explained, with the download URL, not silent."""
    assert "jrsoftware.org/isdl.php" in bat_text, (
        "the Inno Setup download URL must be printed"
    )
    assert "winget install JRSoftware.InnoSetup" in bat_text
    # It must fail loudly rather than continuing.
    missing_block = bat_text[bat_text.index("INNO SETUP WAS NOT FOUND"):]
    assert "goto :fail" in missing_block[:2000]


def test_bat_fails_when_the_application_build_is_missing(bat_text):
    assert "dist\\ShopAdmin\\ShopAdmin.exe" in bat_text
    assert "ERROR" in bat_text


def test_bat_warns_when_the_service_build_is_missing(bat_text):
    assert "ShopSystem.exe" in bat_text
    assert "build_exe.bat" in bat_text, "it should tell the user how to build the service"


def test_bat_pauses_so_a_double_clicked_window_does_not_vanish(bat_text):
    assert bat_text.count("pause") >= 2, (
        "a double-clicked build script must not close before the user reads it"
    )


# --------------------------------------------------------------------------
# installer readme
# --------------------------------------------------------------------------
def test_installer_readme_is_persian_and_covers_the_essentials():
    text = INSTALLER_README.read_text(encoding="utf-8")
    persian = re.compile(r"[\u0600-\u06FF]")
    assert len(persian.findall(text)) > 400, "the readme must be substantially Persian"

    lowered = text
    assert "ShopAdminSetup.exe" in lowered, "how to run the installer"
    assert "Program Files" in lowered or "%LOCALAPPDATA%" in lowered, "where it installs"
    assert "حذف" in lowered, "how to uninstall"
    assert "میزکار" in lowered, "the Desktop shortcut"
    assert "منوی شروع" in lowered, "the Start Menu entry"


def test_installer_readme_explains_both_install_modes():
    text = INSTALLER_README.read_text(encoding="utf-8")
    assert "فقط برای من" in text, "per-user mode must be explained"
    assert "برای همهٔ کاربران" in text, "per-machine mode must be explained"


def test_installer_readme_explains_that_user_data_survives():
    text = INSTALLER_README.read_text(encoding="utf-8")
    assert "پاک نمی‌شود" in text or "دستی" in text, (
        "the readme must say that %LOCALAPPDATA%\\ShopAdmin is kept"
    )


# --------------------------------------------------------------------------
# the two installers
# --------------------------------------------------------------------------
def test_client_installer_has_no_server(iss_text):
    files = _section(iss_text, "[Files]")
    assert "ShopSystem" not in files, "staff computers must not get the server"
    assert "--server-setup" not in iss_text
    assert "schtasks" not in iss_text.lower()


def test_server_installer_identity(server_iss):
    setup = _section(server_iss, "[Setup]")
    assert _directives(setup, "OutputBaseFilename") == ["ShopServerSetup"]
    assert _directives(setup, "PrivilegesRequired") == ["admin"]
    assert "ShopServer" in _directives(setup, "DefaultDirName")[0]
    client_id = _directives(_section(preprocess(ISS_PATH.read_text(encoding="utf-8"), set()),
                                     "[Setup]"), "AppId")[0]
    assert _directives(setup, "AppId")[0] != client_id, "two separate products"


def test_server_installer_never_ships_local_state(server_iss):
    files = _section(server_iss, "[Files]")
    line = next(l for l in _lines(files) if "ShopSystem\\*" in l)
    for pattern in (".env", "*.db", "*.log", "tls\\*"):
        assert pattern in line, f"{pattern} must be excluded from the server files"


def test_server_installer_runs_the_setup_wizard(server_iss):
    run = _section(server_iss, "[Run]")
    assert "--server-setup" in run and "postinstall" in run
    icons = _section(server_iss, "[Icons]")
    assert "--server-setup" in icons, "a Start Menu entry to re-run the server setup"


def test_server_uninstall_removes_task_and_firewall_but_keeps_data(server_iss):
    body = _section(server_iss, "[UninstallRun]")
    assert "/Delete /TN" in body and "firewall delete rule" in body
    assert "--uninstall-service" in body, "the Windows service is removed"
    assert "RunOnceId" in body
    code = _section(server_iss, "[Code]")
    assert "'stop {#ServerTask}'" in code, "an upgrade stops the service before copying"
    assert "--install-service" in code, "an old boot task is moved to the service"
    values = " ".join(l for l in _lines(_section(server_iss, "[UninstallDelete]"))
                      if not l.startswith(";")).lower()
    assert "programdata" not in values, "server data must survive an uninstall"


def test_server_checks_odbc_and_stops_the_server_for_upgrades(server_iss):
    code = server_iss.split("[Code]", 1)[1]
    assert "ODBC Driver 17 for SQL Server" in code
    assert "/End /TN" in code and "taskkill" in code


def test_both_installers_close_a_running_shopadmin(iss_text, server_iss):
    for text in (iss_text, server_iss):
        assert _directives(_section(text, "[Setup]"), "AppMutex") == ["ShopAdminRunning"]


def test_build_time_check_for_the_server_exe(raw_iss):
    assert "#error" in raw_iss and "build_exe.bat" in raw_iss
    code = raw_iss.split("[Code]", 1)[1]
    assert "STAGING_DIR" not in code, "the staging folder does not exist on the customer's PC"


def test_bat_builds_both_installers(bat_text):
    assert "/DSERVER" in bat_text
    assert "ShopServerSetup.exe" in bat_text
