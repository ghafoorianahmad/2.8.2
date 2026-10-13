; =====================================================================
;  ShopAdmin / ShopServer  —  Inno Setup script  (Unicode, Persian UI text)
;
;  One script, two installers (build_installer.bat compiles both):
;
;    iscc ShopAdmin.iss            -> ShopAdminSetup.exe   staff computers:
;                                     only the management program, no admin
;                                     rights needed (per-user by default).
;    iscc /DSERVER ShopAdmin.iss   -> ShopServerSetup.exe  the server computer
;                                     (where the accounting SQL Server runs):
;                                     the server + the management program,
;                                     needs administrator rights, and finishes
;                                     with the Persian server setup wizard.
;
;  Layout produced by build_installer.bat (staging folder):
;      staging\ShopAdmin\        <- the --onedir PyInstaller build
;      staging\ShopSystem\       <- the server build (ShopServer only)
;      staging\README.txt        <- end-user Persian readme
;      staging\installer_readme.txt
; =====================================================================

#define MyAppName "ShopAdmin"
#define MyAppNameFa "مدیریت فروشگاه"
#define MyAppVersion "2.4.0"
#define MyAppPublisher "فروشگاه"
#define MyAppExeName "ShopAdmin.exe"
#define MyServiceExeName "ShopSystem.exe"
#define ServerTask "ShopServer"

; STAGING_DIR is passed by build_installer.bat with /DSTAGING_DIR=... ; the
; default keeps a manual `iscc ShopAdmin.iss` run working from the project root.
#ifndef STAGING_DIR
  #define STAGING_DIR "..\build\installer_staging"
#endif

; Checked when the installer is BUILT. (Checking at install time would look
; for the build folder on the customer's computer and always fail.)
#ifdef SERVER
  #if !FileExists(STAGING_DIR + "\ShopSystem\" + MyServiceExeName)
    #error ShopSystem.exe is missing from the staging folder - run shopsystem\build_exe.bat first
  #endif
#endif

[Setup]
#ifdef SERVER
; A different AppId: the server package is its own product in "Apps & features".
AppId={{5C9E2B14-7A3D-4F68-B0C1-2D8E6F4A9B37}
AppName=ShopServer
AppVerName=سرور فروشگاه {#MyAppVersion}
UninstallDisplayName=سرور فروشگاه
OutputBaseFilename=ShopServerSetup
DefaultDirName={autopf}\ShopServer
DefaultGroupName=سرور فروشگاه
; Registering the Windows service, a firewall rule and a locked data folder all
; need an administrator.
PrivilegesRequired=admin
#else
; A stable AppId keeps upgrades in place instead of installing side by side.
AppId={{8F3A7C21-4B6E-4D52-9A18-6C2E5D9B7F41}
AppName={#MyAppName}
AppVerName={#MyAppNameFa} {#MyAppVersion}
UninstallDisplayName={#MyAppNameFa}
OutputBaseFilename=ShopAdminSetup
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppNameFa}
; --- per-user by default, per-machine when the user has admin rights ----
; PrivilegesRequired=lowest + OverridesAllowed=dialog gives the user a choice
; page and defaults to the safe per-user install.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
#endif
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
DisableProgramGroupPage=yes
AllowNoIcons=yes

; --- a running copy is closed before files are replaced -----------------
; ShopAdmin holds this named mutex while it runs (it lives in the tray).
AppMutex=ShopAdminRunning
CloseApplications=yes
RestartApplications=no

; --- output ---------------------------------------------------------------
OutputDir=..\dist\installer
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
; Inno Setup has no Persian language file: its stock buttons stay English,
; every message we control is Persian.
ShowLanguageDialog=no

; --- uninstall ------------------------------------------------------------
UninstallDisplayIcon={app}\{#MyAppExeName}
CreateUninstallRegKey=yes
DisableWelcomePage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
english.CreateDesktopIcon=ایجاد میان‌بر روی میزکار
english.LaunchAfterInstall=اجرای «مدیریت فروشگاه» پس از نصب
english.ReadMeFirst=مطالعهٔ «راهنمای نصب» پس از نصب
english.AdditionalIcons=میان‌برهای بیشتر:
english.ServerSetupNow=راه‌اندازی سرور فروشگاه (پایگاه‌داده، شبکه، مدیر کل)
english.OdbcMissing=درایور «ODBC Driver 17 for SQL Server» روی این رایانه نصب نیست. سرور بدون آن به حسابداری وصل نمی‌شود. آن را از سایت مایکروسافت نصب کنید (می‌توانید نصب را ادامه دهید و بعداً راه‌اندازی سرور را از منوی شروع اجرا کنید). ادامه می‌دهید؟

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "readme"; Description: "{cm:ReadMeFirst}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
#ifndef SERVER
Name: "launchapp"; Description: "{cm:LaunchAfterInstall}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
#endif

[Files]
; ---- the ShopAdmin desktop application --------------------------------
Source: "{#STAGING_DIR}\ShopAdmin\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

#ifdef SERVER
; ---- the server (API + bots), kept in a sub-folder -----------------------
; Local config/state from the developer's build folder must never ship
; (build_installer.bat also strips them from staging and checks). The real
; configuration lives in %ProgramData%\ShopServer, written by the setup wizard.
Source: "{#STAGING_DIR}\ShopSystem\*"; DestDir: "{app}\ShopSystem"; \
    Excludes: ".env,*.db,*.db-journal,*.log,*.log.*,tls\*"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
#endif

; ---- documentation ----------------------------------------------------
Source: "{#STAGING_DIR}\README.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#STAGING_DIR}\installer_readme.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#STAGING_DIR}\.env.example"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
; Persian shortcut names, as required.
Name: "{group}\{#MyAppNameFa}"; Filename: "{app}\{#MyAppExeName}"; \
    WorkingDir: "{app}"; Comment: "کنسول مدیریت فروشگاه"
Name: "{group}\راهنمای نصب"; Filename: "{app}\installer_readme.txt"
#ifdef SERVER
Name: "{group}\راه‌اندازی سرور فروشگاه"; Filename: "{app}\{#MyAppExeName}"; \
    Parameters: "--server-setup"; WorkingDir: "{app}"; Comment: "تنظیم پایگاه‌داده، شبکه و مدیر کل"
Name: "{group}\حذف سرور فروشگاه"; Filename: "{uninstallexe}"
#else
Name: "{group}\حذف {#MyAppNameFa}"; Filename: "{uninstallexe}"
#endif
Name: "{autodesktop}\{#MyAppNameFa}"; Filename: "{app}\{#MyAppExeName}"; \
    WorkingDir: "{app}"; Tasks: desktopicon

[Run]
#ifdef SERVER
; The server setup wizard. The installer already runs as administrator, so
; the wizard inherits that right (no second UAC prompt).
Filename: "{app}\{#MyAppExeName}"; Parameters: "--server-setup"; \
    Description: "{cm:ServerSetupNow}"; Flags: nowait postinstall skipifsilent
#else
; Optional: start the program right away.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchAfterInstall}"; \
    Flags: nowait postinstall skipifsilent; Tasks: launchapp
#endif
; "Read me first" — opened when the user leaves the corresponding task ticked.
Filename: "{app}\installer_readme.txt"; Description: "{cm:ReadMeFirst}"; \
    Flags: postinstall shellexec skipifsilent; Tasks: readme

#ifdef SERVER
[UninstallRun]
; Stop and remove what the setup wizard registered: the Windows service
; ShopServer (and its grants), the firewall rule, and the boot task of older
; versions. The data folder %ProgramData%\ShopServer (configuration, databases,
; certificate, logs, backups) is deliberately kept: a reinstall continues with
; the same data and keys.
Filename: "{app}\ShopSystem\{#MyServiceExeName}"; \
    Parameters: "--uninstall-service --data-dir ""{commonappdata}\ShopServer"""; \
    Flags: runhidden; RunOnceId: "RemoveService"
Filename: "{sys}\sc.exe"; Parameters: "delete {#ServerTask}"; \
    Flags: runhidden; RunOnceId: "DeleteService"
Filename: "{sys}\schtasks.exe"; Parameters: "/End /TN {#ServerTask}"; \
    Flags: runhidden; RunOnceId: "StopServerTask"
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN {#ServerTask} /F"; \
    Flags: runhidden; RunOnceId: "DeleteServerTask"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name={#ServerTask}"; \
    Flags: runhidden; RunOnceId: "DeleteFirewallRule"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#MyServiceExeName}"; \
    Flags: runhidden; RunOnceId: "KillServer"
#endif

[UninstallDelete]
; Remove stray runtime files, but NEVER user data: %LOCALAPPDATA%\ShopAdmin
; (settings + log) and %ProgramData%\ShopServer are intentionally left behind
; so a reinstall keeps the configuration. Documented in installer_readme.txt.
Type: files; Name: "{app}\shopapi.log"
#ifdef SERVER
Type: dirifempty; Name: "{app}\ShopSystem"
#endif

[Code]
{ ---------------------------------------------------------------------
  Upgrade safety: the running server and ShopAdmin are stopped before files
  are replaced (otherwise Windows keeps the .exe locked). The server
  installer also checks the SQL Server ODBC driver it depends on.
  --------------------------------------------------------------------- }

procedure RunHidden(const FileName, Params: String);
var
  ResultCode: Integer;
begin
  Exec(FileName, Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

#ifdef SERVER
function OdbcDriverInstalled(): Boolean;
begin
  Result := RegKeyExists(HKLM, 'SOFTWARE\ODBC\ODBCINST.INI\ODBC Driver 17 for SQL Server')
    or RegKeyExists(HKLM, 'SOFTWARE\ODBC\ODBCINST.INI\ODBC Driver 18 for SQL Server');
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not OdbcDriverInstalled() then
    Result := MsgBox(CustomMessage('OdbcMissing'), mbConfirmation, MB_YESNO) = IDYES;
end;

function RunHiddenCode(const FileName, Params: String): Integer;
begin
  if not Exec(FileName, Params, '', SW_HIDE, ewWaitUntilTerminated, Result) then
    Result := -1;
end;

var
  ServiceWasInstalled: Boolean;
  TaskWasInstalled: Boolean;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  { Upgrade: stop the server so its files can be replaced. "net stop" waits
    until the service has stopped (a plain kill would make the service
    manager restart it while files are being copied). }
  ServiceWasInstalled := RunHiddenCode(ExpandConstant('{sys}\sc.exe'), 'query {#ServerTask}') = 0;
  TaskWasInstalled := RunHiddenCode(ExpandConstant('{sys}\schtasks.exe'), '/Query /TN {#ServerTask}') = 0;
  if ServiceWasInstalled then
    RunHidden(ExpandConstant('{sys}\net.exe'), 'stop {#ServerTask}');
  RunHidden(ExpandConstant('{sys}\schtasks.exe'), '/End /TN {#ServerTask}');
  RunHidden(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#MyServiceExeName}');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep <> ssPostInstall then
    exit;
  { An older version ran as a boot task: move it to the Windows service now,
    so a silent upgrade does not leave the server on the old mechanism. }
  if TaskWasInstalled and not ServiceWasInstalled then
    RunHidden(ExpandConstant('{app}\ShopSystem\{#MyServiceExeName}'),
      '--install-service --data-dir "' + ExpandConstant('{commonappdata}\ShopServer') + '"');
  { Start the (new) program again; harmless when no service exists yet. }
  if TaskWasInstalled or ServiceWasInstalled then
    RunHidden(ExpandConstant('{sys}\net.exe'), 'start {#ServerTask}');
end;
#else
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
end;
#endif
