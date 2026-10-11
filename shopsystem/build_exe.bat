@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PKG=%~dp0"
if "%PKG:~-1%"=="\" set "PKG=%PKG:~0,-1%"
for %%I in ("%PKG%\..") do set "WS=%%~fI"

set "SRC=%PKG%\build_src"
set "PY=%PKG%\.venv\Scripts\python.exe"
set "MODE=onedir"
if /i "%~1"=="onefile" set "MODE=onefile"

echo ==============================================================
echo   ShopSystem build script            mode: %MODE%
echo ==============================================================
echo   sources : %WS%\shopapi  and  %WS%\shopbots
echo   package : %PKG%
echo.

if not exist "%PY%" goto :novenv
if not exist "%WS%\shopapi\app" goto :nosrc
if not exist "%WS%\shopbots\app" goto :nosrc

rem ------------------------------------------------------------------
echo [1/6] Running the test suites (shopapi, then shopbots) ...
pushd "%WS%\shopapi"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m pytest -q
    if errorlevel 1 (
        echo [ERROR] shopapi tests FAILED - fix them before building.
        popd
        exit /b 1
    )
) else (
    echo [WARN] shopapi\.venv not found - skipping its tests
)
popd

pushd "%WS%\shopbots"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m pytest -q
    if errorlevel 1 (
        echo [ERROR] shopbots tests FAILED - fix them before building.
        popd
        exit /b 1
    )
) else (
    echo [WARN] shopbots\.venv not found - skipping its tests
)
popd

rem ------------------------------------------------------------------
echo [2/6] Collecting the two "app" packages as shopapi_app / shopbots_app ...
if exist "%SRC%" rmdir /s /q "%SRC%"
mkdir "%SRC%"
xcopy /e /i /q /y "%WS%\shopapi\app" "%SRC%\shopapi_app\" >nul
xcopy /e /i /q /y "%WS%\shopbots\app" "%SRC%\shopbots_app\" >nul
for /d /r "%SRC%" %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"

rem The user's real configuration must survive a rebuild: PyInstaller
rem (--noconfirm) wipes the output folder, so rescue .env, the databases
rem and the log BEFORE it runs. KEEP is outside build\ and dist\.
set "OUT=%PKG%\dist\ShopSystem"
if /i "%MODE%"=="onefile" set "OUT=%PKG%\dist"
set "KEEP=%PKG%\.rebuild_keep"
if exist "%KEEP%" (
    echo [ERROR] %KEEP% already exists - a previous build was interrupted.
    echo         Copy its files back into %OUT% by hand, delete it, then rebuild.
    exit /b 1
)
mkdir "%KEEP%"
if exist "%OUT%\.env" copy /y "%OUT%\.env" "%KEEP%\.env" >nul
if exist "%OUT%\shopapi.db" copy /y "%OUT%\shopapi.db" "%KEEP%\shopapi.db" >nul
if exist "%OUT%\shopbots.db" copy /y "%OUT%\shopbots.db" "%KEEP%\shopbots.db" >nul
if exist "%OUT%\app.log" copy /y "%OUT%\app.log" "%KEEP%\app.log" >nul

rem ------------------------------------------------------------------
echo [3/6] Running PyInstaller (%MODE%) - this takes a few minutes ...
"%PY%" -m PyInstaller ^
    --noconfirm --clean ^
    --name ShopSystem ^
    --%MODE% ^
    --console ^
    --paths "%SRC%" ^
    --hidden-import shopapi_app.main ^
    --hidden-import shopbots_app.main ^
    --collect-submodules uvicorn ^
    --collect-submodules anyio ^
    --collect-submodules starlette ^
    --collect-submodules shopapi_app ^
    --collect-submodules shopbots_app ^
    --collect-data certifi ^
    --hidden-import uvicorn.logging ^
    --hidden-import uvicorn.loops ^
    --hidden-import uvicorn.loops.auto ^
    --hidden-import uvicorn.loops.asyncio ^
    --hidden-import uvicorn.protocols ^
    --hidden-import uvicorn.protocols.http ^
    --hidden-import uvicorn.protocols.http.auto ^
    --hidden-import uvicorn.protocols.http.h11_impl ^
    --hidden-import uvicorn.protocols.websockets ^
    --hidden-import uvicorn.protocols.websockets.auto ^
    --hidden-import uvicorn.lifespan ^
    --hidden-import uvicorn.lifespan.on ^
    --hidden-import uvicorn.lifespan.off ^
    --hidden-import dotenv ^
    --hidden-import server_tls ^
    --collect-submodules cryptography ^
    --hidden-import sqlite3 ^
    --hidden-import pyodbc ^
    --hidden-import httpx ^
    --add-data "%SRC%\shopbots_app\messages.fa.json;shopbots_app" ^
    --hidden-import httpcore ^
    --hidden-import anyio._backends._asyncio ^
    --hidden-import email.mime.multipart ^
    --exclude-module tkinter ^
    --exclude-module matplotlib ^
    --exclude-module numpy ^
    --exclude-module pandas ^
    --exclude-module PyQt5 ^
    --exclude-module pytest ^
    launcher.py
if errorlevel 1 goto :buildfail

rem ------------------------------------------------------------------
echo [4/6] Copying .env.example and README.txt next to the executable ...
if not exist "%OUT%" mkdir "%OUT%"

copy /y "%PKG%\.env.example" "%OUT%\.env.example" >nul
copy /y "%PKG%\README.txt" "%OUT%\README.txt" >nul
if exist "%PKG%\NOTES.md" copy /y "%PKG%\NOTES.md" "%OUT%\NOTES.md" >nul

if exist "%KEEP%\.env" (
    copy /y "%KEEP%\.env" "%OUT%\.env" >nul
    echo        kept your existing .env
)
if exist "%KEEP%\shopapi.db" copy /y "%KEEP%\shopapi.db" "%OUT%\shopapi.db" >nul
if exist "%KEEP%\shopbots.db" copy /y "%KEEP%\shopbots.db" "%OUT%\shopbots.db" >nul
if exist "%KEEP%\app.log" copy /y "%KEEP%\app.log" "%OUT%\app.log" >nul
rmdir /s /q "%KEEP%" 2>nul

echo [5/6] Build finished.
echo.
echo   Output folder : %OUT%
echo   Executable    : %OUT%\ShopSystem.exe
echo.
echo [6/6] Next steps:
echo   1. copy  .env.example  to  .env   in that folder
echo   2. fill in the tokens, API keys and database details
echo   3. double-click ShopSystem.exe  (keep the console window open)
echo.
exit /b 0

:novenv
echo [ERROR] No virtual environment found at %PY%
echo         Run these first, from this folder:
echo             python -m venv .venv
echo             .venv\Scripts\python.exe -m pip install -r requirements.txt
exit /b 1

:nosrc
echo [ERROR] Could not find the source projects.
echo         Expected: %WS%\shopapi\app  and  %WS%\shopbots\app
echo         Adjust WS at the top of this script if they live elsewhere.
exit /b 1

:buildfail
echo.
echo [ERROR] PyInstaller failed. See the messages above and NOTES.md.
if not exist "%OUT%" mkdir "%OUT%"
for %%F in (.env shopapi.db shopbots.db app.log) do if exist "%KEEP%\%%F" copy /y "%KEEP%\%%F" "%OUT%\%%F" >nul
rmdir /s /q "%KEEP%" 2>nul
exit /b 1
