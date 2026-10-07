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
set "STAGING_CLIENT=%~dp0build\installer_staging_client"
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

REM ---- 3. build the application (two variants) -------------------------
REM  full   -> dist\ShopAdmin\         with the server setup (ShopServerSetup)
REM  client -> dist\client\ShopAdmin\  staff computers: no server setup and no
REM            reference to the server program at all (checked by the build)
echo [1/4] Building the ShopAdmin application (server + client variants) ...
"%PY%" build_shopadmin.py --clean
if errorlevel 1 goto :fail
if not exist "dist\ShopAdmin\ShopAdmin.exe" (
    echo ERROR: dist\ShopAdmin\ShopAdmin.exe was not produced.
    goto :fail
)
"%PY%" build_shopadmin.py --clean --variant client
if errorlevel 1 goto :fail
if not exist "dist\client\ShopAdmin\ShopAdmin.exe" (
    echo ERROR: dist\client\ShopAdmin\ShopAdmin.exe was not produced.
    goto :fail
)

REM ---- 4. verify the server build --------------------------------------
echo.
echo [2/4] Checking the ShopSystem server build ...
if not exist "%SHOPSYSTEM_DIST%\ShopSystem.exe" (
    echo =====================================================================
    echo   SHOPsystem SERVER BUILD NOT FOUND
    echo =====================================================================
    echo.
    echo   Expected: %SHOPSYSTEM_DIST%\ShopSystem.exe
    echo.
    echo   Build it first:
    echo       cd ..\shopsystem
    echo       build_exe.bat
    echo.
    echo   If you continue, only ShopAdminSetup.exe ^(staff computers^) is
    echo   built; ShopServerSetup.exe needs the server build.
    echo =====================================================================
    if defined SHOP_NOPAUSE goto :fail
    choice /C YN /M "Continue without ShopSystem.exe"
    if errorlevel 2 goto :fail
)

REM ---- 5. stage everything ---------------------------------------------
REM  installer_staging        = server package (full ShopAdmin + ShopSystem)
REM  installer_staging_client = staff package  (client ShopAdmin only)
echo.
echo [3/4] Staging files ...
for %%S in ("%STAGING%" "%STAGING_CLIENT%") do (
    if exist "%%~S" rmdir /S /Q "%%~S"
    mkdir "%%~S\ShopAdmin" || goto :fail
)
mkdir "%STAGING%\ShopSystem" || goto :fail

xcopy /E /I /Y /Q "dist\ShopAdmin\*" "%STAGING%\ShopAdmin\" >nul
if errorlevel 1 (
    echo ERROR: could not copy the ShopAdmin build into the staging folder.
    goto :fail
)
xcopy /E /I /Y /Q "dist\client\ShopAdmin\*" "%STAGING_CLIENT%\ShopAdmin\" >nul
if errorlevel 1 (
    echo ERROR: could not copy the client build into the staging folder.
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
for %%S in ("%STAGING%" "%STAGING_CLIENT%") do (
    for %%P in (.env *.db *.db-journal *.log *.log.*) do (
        del /S /Q /F "%%~S\%%P" >nul 2>&1
    )
    dir /S /B /A-D "%%~S\.env" "%%~S\*.db" "%%~S\*.log" >nul 2>&1
    if not errorlevel 1 (
        echo ERROR: local config/state is still in the staging folder:
        dir /S /B /A-D "%%~S\.env" "%%~S\*.db" "%%~S\*.log" 2>nul
        goto :fail
    )
    copy /Y "README.txt" "%%~S\README.txt" >nul
    copy /Y "installer\installer_readme.txt" "%%~S\installer_readme.txt" >nul
)
REM  .env.example describes the server configuration: server package only.
if exist ".env.example" copy /Y ".env.example" "%STAGING%\.env.example" >nul

if not exist "%STAGING_CLIENT%\ShopAdmin\ShopAdmin.exe" (
    echo ERROR: the staged client is missing ShopAdmin.exe.
    goto :fail
)

REM ---- 6. compile the installers ---------------------------------------
REM  ShopAdminSetup.exe  = staff computers (management program only)
REM  ShopServerSetup.exe = the server computer (server + management program)
echo.
echo [4/4] Compiling the installers with Inno Setup ...
if not exist "%INSTALLER_OUT%" mkdir "%INSTALLER_OUT%" >nul
"%ISCC%" /Qp /DSTAGING_DIR="%STAGING_CLIENT%" "installer\ShopAdmin.iss"
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

set "SERVER_BUILT="
if exist "%STAGING%\ShopSystem\ShopSystem.exe" (
    "%ISCC%" /Qp /DSERVER /DSTAGING_DIR="%STAGING%" "installer\ShopAdmin.iss"
    if errorlevel 1 (
        echo.
        echo ERROR: Inno Setup failed to compile the server installer.
        goto :fail
    )
    set "SERVER_BUILT=1"
) else (
    echo WARNING: ShopSystem.exe was not staged - ShopServerSetup.exe was NOT built.
)

echo.
echo =====================================================================
echo   DONE
echo.
echo   Staff computers : %INSTALLER_OUT%\ShopAdminSetup.exe
if defined SERVER_BUILT echo   Server computer : %INSTALLER_OUT%\ShopServerSetup.exe
echo.
echo   On the server (the computer with the accounting SQL Server) run
echo   ShopServerSetup.exe as administrator; it ends with the server setup.
echo   On every other computer run ShopAdminSetup.exe and enter the server
echo   address and fingerprint shown at the end of the server setup.
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
