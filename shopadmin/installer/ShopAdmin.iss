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
#define MyAppVersion "2.16.0"
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
; v2.9.4: D:\ShopServer when the computer has a D: disk (else Program Files);
; an upgrade keeps the folder chosen the first time (UsePreviousAppDir).
DefaultDirName={code:DefaultAppDir|ShopServer}
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
; v2.9.4: D:\ShopAdmin when the computer has a D: disk (else Program Files)
DefaultDirName={code:DefaultAppDir|{#MyAppName}}
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
; v2.9.4: the program folder is always chosen on its own page (on an upgrade
; it shows the folder used so far)
DisableDirPage=no
UsePreviousAppDir=yes

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
english.DataDirTitle=پوشهٔ داده‌های سرور
english.DataDirDesc=تنظیمات، پایگاه‌داده‌های خود فروشگاه، رسیدها، گواهی امنیتی و پشتیبان‌ها کجا نگه داشته شوند؟
english.DataDirLabel=پوشهٔ داده‌ها (فقط مدیران ویندوز و حساب سرویس سرور به آن دسترسی خواهند داشت):
english.DataDirMove=انتقال امن داده‌های فعلی به پوشهٔ بالا (اول رونوشت و آزمایش؛ پوشهٔ قبلی فقط پس از کار کردن سرور پاک می‌شود)
english.DataDirCurrent=داده‌های فعلی سرور در این پوشه است:
english.DataDirRoot=ریشهٔ درایو پذیرفته نیست؛ یک پوشه انتخاب کنید (مثلاً D:\ShopServerData).
english.DataDirInsideApp=پوشهٔ داده‌ها نباید داخل پوشهٔ برنامه باشد.
english.DataMoving=انتقال امن داده‌های سرور به پوشهٔ تازه…
english.DataMoveFailed=انتقال داده‌ها انجام نشد؛ سرور با همان پوشهٔ قبلی کار می‌کند و هیچ داده‌ای پاک نشد.
english.DataKeptOld=داده‌ها جابه‌جا نشدند و سرور با همان پوشهٔ فعلی کار می‌کند:
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
; ---- least-privilege SQL role shop_app (v2.5.0) -------------------------
; Run by the DBA/owner on the server: deploy\grant_shop_app.ps1 -Server ... -Database ...
; (dry run without -Apply). Paths are relative to this .iss (installer\).
Source: "..\..\shopapi\sql\grant_shop_app.sql"; DestDir: "{app}\sql"; Flags: ignoreversion
Source: "..\..\shopapi\sql\verify_permissions.sql"; DestDir: "{app}\sql"; Flags: ignoreversion
Source: "..\..\shopsystem\deploy\grant_shop_app.ps1"; DestDir: "{app}"; Flags: ignoreversion
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
Name: "{group}\تنظیمات سرور"; Filename: "{app}\{#MyAppExeName}"; \
    Parameters: "--server-settings"; WorkingDir: "{app}"; \
    Comment: "پایگاه‌داده، ثبت واقعی، شبکه و ربات‌ها — با مقدارهای فعلی"
Name: "{group}\حذف سرور فروشگاه"; Filename: "{uninstallexe}"
#else
Name: "{group}\حذف {#MyAppNameFa}"; Filename: "{uninstallexe}"
#endif
#ifdef SERVER
; v2.8.1: on the server the desktop shortcut is «تنظیمات سرور»: the setup wizard
; again, filled with the current values (no reinstall). The console stays in
; the Start menu.
Name: "{autodesktop}\تنظیمات سرور"; Filename: "{app}\{#MyAppExeName}"; \
    Parameters: "--server-settings"; WorkingDir: "{app}"; Tasks: desktopicon; \
    Comment: "پایگاه‌داده، ثبت واقعی، شبکه و ربات‌ها — با مقدارهای فعلی"
#else
Name: "{autodesktop}\{#MyAppNameFa}"; Filename: "{app}\{#MyAppExeName}"; \
    WorkingDir: "{app}"; Tasks: desktopicon
#endif

[Run]
#ifdef SERVER
; The server setup wizard. The installer already runs as administrator, so
; the wizard inherits that right (no second UAC prompt).
; v2.15.0: only on a NEW server. An upgrade keeps every setting as it is (the
; database, the allowed list, «ثبت واقعی», …); «تنظیمات سرور» changes them.
Filename: "{app}\{#MyAppExeName}"; Parameters: "--server-setup"; \
    Description: "{cm:ServerSetupNow}"; Flags: nowait postinstall skipifsilent; \
    Check: IsNewServer
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
; versions. The data folder (v2.9.4: the one chosen at install, e.g. D:\ShopServerData;
; configuration, databases,
; certificate, logs, backups) is deliberately kept: a reinstall continues with
; the same data and keys.
Filename: "{app}\ShopSystem\{#MyServiceExeName}"; \
    Parameters: "--uninstall-service --data-dir ""{code:CurrentDataDir|}"""; \
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

#ifdef SERVER
[InstallDelete]
; v2.8.1: the server package's old desktop shortcut opened the console; it is
; replaced by «تنظیمات سرور». (Only the all-users desktop of this admin install:
; a per-user «مدیریت فروشگاه» from ShopAdminSetup is left alone.)
Type: files; Name: "{commondesktop}\{#MyAppNameFa}.lnk"
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

{ v2.9.4: D:\<name> when D: is a fixed disk, else Program Files (both installers). }
function GetDriveTypeW(lpRootPathName: String): Cardinal;
  external 'GetDriveTypeW@kernel32.dll stdcall';

function HasFixedD(): Boolean;
begin
  Result := GetDriveTypeW('D:\') = 3;
end;

function DefaultAppDir(Param: String): String;
begin
  if HasFixedD() then
    Result := 'D:\' + Param
  else
    Result := ExpandConstant('{autopf}\') + Param;
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

{ ---------------------------------------------------------------------
  v2.9.4: the data folder (default D:\ShopServerData, else
  %ProgramData%\ShopServer). The choice is kept in
  HKLM\SOFTWARE\ShopServer\DataDir, read by ShopSystem and the server setup,
  and offered again on every upgrade. Data in another folder (2.9.3 and older:
  %ProgramData%\ShopServer) is moved by ShopSystem --move-data: copy, SHA-256
  check, switch, health check, and only then the old folder is deleted; on any
  failure everything goes back and nothing is deleted.
  --------------------------------------------------------------------- }
const
  DataKey = 'SOFTWARE\ShopServer';
  DataValue = 'DataDir';

var
  ServiceWasInstalled: Boolean;
  TaskWasInstalled: Boolean;
  DataPage: TInputDirWizardPage;
  MoveCheck: TNewCheckBox;
  CurrentLabel: TNewStaticText;
  OldDataDir: String;
  FinalDataDir: String;

function RegisteredDataDir(): String;
begin
  Result := '';
  if not RegQueryStringValue(HKLM, DataKey, DataValue, Result) then
    Result := '';
end;

{ Where the server's data is today ('' = a new server). }
function ExistingDataDir(): String;
begin
  Result := RegisteredDataDir();
  if (Result <> '') and FileExists(AddBackslash(Result) + '.env') then
    exit;
  Result := ExpandConstant('{commonappdata}\ShopServer');
  if not FileExists(AddBackslash(Result) + '.env') then
    Result := '';
end;

{ v2.15.0: no server settings on this computer yet (an upgrade has them). }
function IsNewServer(): Boolean;
begin
  Result := OldDataDir = '';
end;

function DefaultDataDir(): String;
begin
  Result := RegisteredDataDir();
  if Result <> '' then
    exit;                                   { an upgrade: the folder chosen before }
  if HasFixedD() then
    Result := 'D:\ShopServerData'
  else
    Result := ExpandConstant('{commonappdata}\ShopServer');
end;

{ For [UninstallRun]: the folder in use (the registry, else the old default). }
function CurrentDataDir(Param: String): String;
begin
  Result := RegisteredDataDir();
  if Result = '' then
    Result := ExpandConstant('{commonappdata}\ShopServer');
end;

function SameDir(const A, B: String): Boolean;
begin
  Result := CompareText(RemoveBackslashUnlessRoot(A), RemoveBackslashUnlessRoot(B)) = 0;
end;

procedure InitializeWizard();
begin
  OldDataDir := ExistingDataDir();
  DataPage := CreateInputDirPage(wpSelectDir, CustomMessage('DataDirTitle'),
    CustomMessage('DataDirDesc'), CustomMessage('DataDirLabel'), False, 'ShopServerData');
  DataPage.Add('');
  DataPage.Values[0] := DefaultDataDir();
  CurrentLabel := TNewStaticText.Create(DataPage);
  CurrentLabel.Parent := DataPage.Surface;
  CurrentLabel.Top := DataPage.Edits[0].Top + DataPage.Edits[0].Height + ScaleY(14);
  CurrentLabel.Width := DataPage.SurfaceWidth;
  CurrentLabel.AutoSize := False;
  CurrentLabel.WordWrap := True;
  CurrentLabel.Height := ScaleY(32);
  CurrentLabel.Caption := CustomMessage('DataDirCurrent') + ' ' + OldDataDir;
  CurrentLabel.Visible := OldDataDir <> '';
  MoveCheck := TNewCheckBox.Create(DataPage);
  MoveCheck.Parent := DataPage.Surface;
  MoveCheck.Top := CurrentLabel.Top + CurrentLabel.Height + ScaleY(6);
  MoveCheck.Width := DataPage.SurfaceWidth;
  MoveCheck.Height := ScaleY(34);
  MoveCheck.Caption := CustomMessage('DataDirMove');
  MoveCheck.Checked := True;
  MoveCheck.Visible := OldDataDir <> '';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Folder: String;
begin
  Result := True;
  if CurPageID <> DataPage.ID then
    exit;
  Folder := RemoveBackslashUnlessRoot(Trim(DataPage.Values[0]));
  if (Length(Folder) <= 3) then
  begin
    MsgBox(CustomMessage('DataDirRoot'), mbError, MB_OK);
    Result := False;
    exit;
  end;
  if Pos(Lowercase(AddBackslash(WizardDirValue())), Lowercase(AddBackslash(Folder))) = 1 then
  begin
    MsgBox(CustomMessage('DataDirInsideApp'), mbError, MB_OK);
    Result := False;
  end;
end;

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

{ The program folder: SYSTEM and Administrators full, users read/run only (a
  D:\ folder would otherwise inherit "Authenticated Users: Modify", and the
  service runs ShopSystem.exe from here). Children inherit (never /T with
  /inheritance:r on files: that leaves them with an empty ACL). }
procedure LockProgramFolder();
var
  App: String;
begin
  App := ExpandConstant('{app}');
  RunHidden(ExpandConstant('{sys}\icacls.exe'), '"' + App + '" /inheritance:r /grant:r' +
    ' *S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F *S-1-5-32-545:(OI)(CI)RX' +
    ' *S-1-5-11:(OI)(CI)RX *S-1-5-6:(OI)(CI)RX /C /Q');
  RunHidden(ExpandConstant('{sys}\icacls.exe'), '"' + App + '\*" /reset /T /C /Q');
end;

{ Decide the data folder and move the data there when asked; the result is in
  FinalDataDir and in the registry. }
procedure SettleDataDir();
var
  Wanted, Exe: String;
  Code: Integer;
begin
  Wanted := RemoveBackslashUnlessRoot(Trim(DataPage.Values[0]));
  FinalDataDir := Wanted;
  Exe := ExpandConstant('{app}\ShopSystem\{#MyServiceExeName}');
  if (OldDataDir = '') or SameDir(OldDataDir, Wanted) then
  begin
    ForceDirectories(Wanted);
    RegWriteStringValue(HKLM, DataKey, DataValue, Wanted);
    exit;
  end;
  if not MoveCheck.Checked then
  begin
    FinalDataDir := OldDataDir;               { kept where it is, nothing moved }
    RegWriteStringValue(HKLM, DataKey, DataValue, OldDataDir);
    if not WizardSilent() then
      MsgBox(CustomMessage('DataKeptOld') + ' ' + OldDataDir, mbInformation, MB_OK);
    exit;
  end;
  WizardForm.StatusLabel.Caption := CustomMessage('DataMoving');
  Code := RunHiddenCode(Exe, '--data-dir "' + OldDataDir + '" --move-data "' + Wanted + '"');
  if Code <> 0 then
  begin
    FinalDataDir := OldDataDir;
    if not WizardSilent() then
      MsgBox(CustomMessage('DataMoveFailed'), mbError, MB_OK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep <> ssPostInstall then
    exit;
  LockProgramFolder();
  SettleDataDir();
  { Re-register the service with this program and data folder: it also gives
    the service account its grants again (e.g. the backup sub-folder, v2.9.4).
    An older version ran as a boot task: this moves it to the service too. }
  if TaskWasInstalled or ServiceWasInstalled then
  begin
    RunHidden(ExpandConstant('{app}\ShopSystem\{#MyServiceExeName}'),
      '--install-service --data-dir "' + FinalDataDir + '"');
    RunHidden(ExpandConstant('{sys}\net.exe'), 'start {#ServerTask}');
  end;
end;
#else
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
end;
#endif
