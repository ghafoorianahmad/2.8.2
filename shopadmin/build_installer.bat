@echo off
REM =====================================================================
REM  ShopAdmin — build the Windows installer (ShopAdminSetup.exe)
REM
REM  Steps:
REM    1. PyInstaller build of ShopAdmin           (build_shopadmin.py)
REM    2. copy ShopAdmin + ShopSystem into a staging folder
REM    3. compile installer\ShopAdmin.iss with Inno Setup's iscc.exe
REM    4. leave dist\installer\ShopAdminSetup.exe
REM
REM  Usage:  build_installer.bat
REM =====================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "STAGING=%~dp0build\installer_staging"
set "INSTALLER_OUT=%~dp0dist\installer"
set "SHOPSYSTEM_DIST=%~dp0..\shopsystem\dist\ShopSystem"

echo.
echo =====================================================================
echo   Building ShopAdminSetup.exe
echo =====================================================================
echo.

REM ---- 1. locate Python -------------------------------------------------
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY ( where py >nul 2>&1 && set "PY=py -3" )
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY (
    echo ERROR: Python 3.10+ was not found. Install it from
    echo        https://www.python.org/downloads/windows/
    goto :fail
)
if not exist ".venv\Scripts\python.exe" (
    echo [0/4] Creating the virtual environment ...
    %PY% -m venv .venv
    if errorlevel 1 goto :fail
)
set "PY=.venv\Scripts\python.exe"

REM ---- 2. locate Inno Setup's compiler ---------------------------------
REM  Checked in order: explicit override, PATH, then the usual install dirs.
set "ISCC="
if defined INNO_SETUP_ISCC if exist "%INNO_SETUP_ISCC%" set "ISCC=%INNO_SETUP_ISCC%"
if not defined ISCC (
    for %%I in (iscc.exe) do if not defined ISCC set "ISCC=%%~$PATH:I"
)
if not defined ISCC (
    for %%D in (
        "%ProgramFiles(x86)%\Inno Setup 6"
        "%ProgramFiles%\Inno Setup 6"
        "%ProgramFiles(x86)%\Inno Setup 7"
        "%ProgramFiles%\Inno Setup 7"
        "%LOCALAPPDATA%\Programs\Inno Setup 6"
        "%LOCALAPPDATA%\Programs\Inno Setup 7"
    ) do (
        if not defined ISCC if exist "%%~D\ISCC.exe" set "ISCC=%%~D\ISCC.exe"
    )
)
if not defined ISCC (
    echo =====================================================================
    echo   INNO SETUP WAS NOT FOUND ON THIS COMPUTER
    echo =====================================================================
    echo.
    echo   The installer compiler ^(iscc.exe^) is required to build
    echo   ShopAdminSetup.exe. It is free software.
    echo.
    echo   Download and install it from:
    echo       https://jrsoftware.org/isdl.php
    echo.
    echo   Or install it with winget:
    echo       winget install JRSoftware.InnoSetup
    echo.
    echo   If it is installed somewhere unusual, point this script at it:
    echo       set INNO_SETUP_ISCC=C:\path\to\ISCC.exe
    echo.
    echo   Nothing else was changed; the application build was not started.
    echo =====================================================================
    goto :fail
)
echo Using Inno Setup compiler: %ISCC%
echo.

REM ---- 3. build the application ----------------------------------------
echo [1/4] Building the ShopAdmin application ...
"%PY%" build_shopadmin.py --clean
if errorlevel 1 goto :fail
if not exist "dist\ShopAdmin\ShopAdmin.exe" (
    echo ERROR: dist\ShopAdmin\ShopAdmin.exe was not produced.
    goto :fail
)

REM ---- 4. verify the service build -------------------------------------
echo.
echo [2/4] Checking the ShopSystem service build ...
if not exist "%SHOPSYSTEM_DIST%\ShopSystem.exe" (
    echo =====================================================================
    echo   SHOPsystem SERVICE BUILD NOT FOUND
    echo =====================================================================
    echo.
    echo   Expected: %SHOPSYSTEM_DIST%\ShopSystem.exe
    echo.
    echo   Build it first:
    echo       cd ..\shopsystem
    echo       build_exe.bat
    echo.
    echo   The installer is built WITHOUT the service if you continue,
    echo   but ShopAdmin will then not be able to start it automatically.
    echo =====================================================================
    choice /C YN /M "Continue without ShopSystem.exe"
    if errorlevel 2 goto :fail
)

REM ---- 5. stage everything ---------------------------------------------
echo.
echo [3/4] Staging files ...
if exist "%STAGING%" rmdir /S /Q "%STAGING%"
mkdir "%STAGING%\ShopAdmin" || goto :fail
mkdir "%STAGING%\ShopSystem" || goto :fail

xcopy /E /I /Y /Q "dist\ShopAdmin\*" "%STAGING%\ShopAdmin\" >nul
if errorlevel 1 (
    echo ERROR: could not copy the ShopAdmin build into the staging folder.
    goto :fail
)
if exist "%SHOPSYSTEM_DIST%\ShopSystem.exe" (
    xcopy /E /I /Y /Q "%SHOPSYSTEM_DIST%\*" "%STAGING%\ShopSystem\" >nul
    if errorlevel 1 (
        echo ERROR: could not copy the ShopSystem build.
        goto :fail
    )
)
REM  The ShopSystem dist folder is also the developer's test folder, so it
REM  may hold a real .env (keys, tokens), databases and logs. Strip them.
for %%P in (.env *.db *.db-journal *.log *.log.*) do (
    del /S /Q /F "%STAGING%\%%P" >nul 2>&1
)
dir /S /B /A-D "%STAGING%\.env" "%STAGING%\*.db" "%STAGING%\*.log" >nul 2>&1
if not errorlevel 1 (
    echo ERROR: local config/state is still in the staging folder:
    dir /S /B /A-D "%STAGING%\.env" "%STAGING%\*.db" "%STAGING%\*.log" 2>nul
    goto :fail
)
copy /Y "README.txt" "%STAGING%\README.txt" >nul
copy /Y "installer\installer_readme.txt" "%STAGING%\installer_readme.txt" >nul
if exist ".env.example" copy /Y ".env.example" "%STAGING%\.env.example" >nul

if not exist "%STAGING%\ShopAdmin\ShopAdmin.exe" (
    echo ERROR: the staged application is missing ShopAdmin.exe.
    goto :fail
)

REM ---- 6. compile the installer ----------------------------------------
echo.
echo [4/4] Compiling the installer with Inno Setup ...
if not exist "%INSTALLER_OUT%" mkdir "%INSTALLER_OUT%" >nul
"%ISCC%" /Qp /DSTAGING_DIR="%STAGING%" "installer\ShopAdmin.iss"
if errorlevel 1 (
    echo.
    echo ERROR: Inno Setup failed to compile installer\ShopAdmin.iss
    echo        See the messages above for the reason.
    goto :fail
)

if not exist "%INSTALLER_OUT%\ShopAdminSetup.exe" (
    echo ERROR: ShopAdminSetup.exe was not produced.
    goto :fail
)

for %%F in ("%INSTALLER_OUT%\ShopAdminSetup.exe") do set "SETUP_SIZE=%%~zF"
echo.
echo =====================================================================
echo   DONE
echo.
echo   Installer: %INSTALLER_OUT%\ShopAdminSetup.exe
echo   Size:      !SETUP_SIZE! bytes
echo.
echo   Give that single file to the shop owner. It installs the program,
echo   the ShopSystem service, the Desktop shortcut and the Start Menu
echo   entry, and registers an uninstaller.
echo =====================================================================
echo.
if not defined SHOP_NOPAUSE pause
exit /b 0

:fail
echo.
echo =====================================================================
echo   BUILD FAILED - see the messages above.
echo =====================================================================
echo.
if not defined SHOP_NOPAUSE pause
exit /b 1
