; =====================================================================
;  ShopAdmin  —  Inno Setup script  (Unicode, Persian UI text)
;
;  Build it with:   build_installer.bat
;  or directly:     iscc.exe installer\ShopAdmin.iss
;
;  Layout produced by build_installer.bat (staging folder):
;      staging\ShopAdmin\        <- the --onedir PyInstaller build
;      staging\ShopSystem\       <- the shopapi service build
;      staging\README.txt        <- end-user Persian readme
;      staging\installer_readme.txt
; =====================================================================

#define MyAppName "ShopAdmin"
#define MyAppNameFa "مدیریت فروشگاه"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "فروشگاه"
#define MyAppExeName "ShopAdmin.exe"
#define MyServiceExeName "ShopSystem.exe"

; STAGING_DIR is passed by build_installer.bat with /DSTAGING=... ; the default
; keeps a manual `iscc ShopAdmin.iss` run working from the project root.
#ifndef STAGING_DIR
  #define STAGING_DIR "..\build\installer_staging"
#endif

[Setup]
; A stable AppId keeps upgrades in place instead of installing side by side.
AppId={{8F3A7C21-4B6E-4D52-9A18-6C2E5D9B7F41}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppNameFa} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}

; --- per-user by default, per-machine when the user has admin rights -----
; PrivilegesRequired=lowest + OverridesAllowed=dialog gives the user a choice
; page ("برای همهٔ کاربران" / "فقط برای من") and defaults to the safe per-user
; install for a small shop.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppNameFa}
DisableProgramGroupPage=yes
AllowNoIcons=yes

; --- output ---------------------------------------------------------------
OutputDir=..\dist\installer
OutputBaseFilename=ShopAdminSetup
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
; The UI itself is in Persian; the built-in wizard dialogs stay in English
; because Inno Setup has no Persian language file, and every custom string we
; control is Persian.
ShowLanguageDialog=no

; --- uninstall ------------------------------------------------------------
UninstallDisplayName={#MyAppNameFa}
UninstallDisplayIcon={app}\{#MyAppExeName}
CreateUninstallRegKey=yes

; --- Persian text rendering ----------------------------------------------
; A left-to-right RTL-ish setup: the Persian strings below are short labels,
; and Inno Setup renders them with the system font.
DisableWelcomePage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
english.CreateDesktopIcon=ایجاد میان‌بر روی میزکار
english.LaunchAfterInstall=اجرای «مدیریت فروشگاه» پس از نصب
english.ReadMeFirst=مطالعهٔ «راهنمای نصب» پس از نصب
english.AdditionalIcons=میان‌برهای بیشتر:
english.ServiceSection=سرویس فروشگاه (ShopSystem)
english.InstallServiceTask=نصب سرویس فروشگاه برای اجرای خودکار با ویندوز (نیازمند دسترسی مدیر)
english.RunAtStartup=اجرای خودکار با ویندوز

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "readme"; Description: "{cm:ReadMeFirst}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "launchapp"; Description: "{cm:LaunchAfterInstall}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; ---- the ShopAdmin desktop application --------------------------------
Source: "{#STAGING_DIR}\ShopAdmin\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

; ---- the shopapi service, kept in a sub-folder ------------------------
; Local config/state from the developer's build folder must never ship
; (build_installer.bat also strips them from staging and checks).
Source: "{#STAGING_DIR}\ShopSystem\*"; DestDir: "{app}\ShopSystem"; \
    Excludes: ".env,*.db,*.db-journal,*.log,*.log.*"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

; ---- documentation ----------------------------------------------------
Source: "{#STAGING_DIR}\README.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#STAGING_DIR}\installer_readme.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#STAGING_DIR}\.env.example"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
; Persian shortcut names, as required.
Name: "{group}\{#MyAppNameFa}"; Filename: "{app}\{#MyAppExeName}"; \
    WorkingDir: "{app}"; Comment: "کنسول مدیریت فروشگاه"
Name: "{group}\راهنمای نصب"; Filename: "{app}\installer_readme.txt"
Name: "{group}\حذف {#MyAppNameFa}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppNameFa}"; Filename: "{app}\{#MyAppExeName}"; \
    WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; "Read me first" — opened when the user leaves the corresponding task ticked.
Filename: "{app}\installer_readme.txt"; Description: "{cm:ReadMeFirst}"; \
    Flags: postinstall shellexec skipifsilent; Tasks: readme

; Optional: start the program right away.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchAfterInstall}"; \
    Flags: nowait postinstall skipifsilent; Tasks: launchapp

[UninstallDelete]
; Remove the service log and any stray runtime files, but NEVER user data:
; %LOCALAPPDATA%\ShopAdmin (settings + log) is intentionally left behind so a
; reinstall keeps the configuration. It is documented in installer_readme.txt.
Type: files; Name: "{app}\shopapi.log"
Type: dirifempty; Name: "{app}\ShopSystem"

[Code]
{ ---------------------------------------------------------------------
  Small helpers so the installer behaves predictably for a non-technical
  user: it verifies the service folder shipped correctly, and it stops a
  running ShopAdmin before replacing files.
  --------------------------------------------------------------------- }

function ServiceFolderExists(): Boolean;
begin
  Result := DirExists(ExpandConstant('{app}\ShopSystem'));
end;

procedure InitializeWizard();
begin
  { Nothing custom to draw: the stock pages plus our Persian task labels. }
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not FileExists(ExpandConstant('{#STAGING_DIR}\ShopSystem\{#MyServiceExeName}')) then
    Result := 'فایل سرویس فروشگاه (ShopSystem.exe) در بستهٔ نصب پیدا نشد.';
end;

{ Ask Windows to close a running instance so an upgrade can replace the exe. }
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
