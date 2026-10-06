@echo off
REM =====================================================================
REM  ShopAdmin build script  (Persian desktop admin console)
REM
REM  Produces:  dist\ShopAdmin\ShopAdmin.exe
REM
REM  Usage:  build_shopadmin.bat
REM =====================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo =====================================================================
echo   Building ShopAdmin ...
echo =====================================================================
echo.

REM ---- 1. find a Python interpreter -----------------------------------
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    where py >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo ERROR: Python 3.10+ was not found on this computer.
    echo        Install Python from https://www.python.org/downloads/windows/
    echo        and make sure "Add python.exe to PATH" is checked.
    goto :fail
)
echo Using interpreter: %PY%
%PY% --version
if errorlevel 1 goto :fail

REM ---- 2. create the virtual environment if needed --------------------
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo [1/4] Creating the virtual environment in .venv ...
    %PY% -m venv .venv
    if errorlevel 1 goto :fail
    set "PY=.venv\Scripts\python.exe"
)

set "PY=.venv\Scripts\python.exe"
set "PIP=%PY% -m pip"

REM ---- 3. install dependencies ----------------------------------------
echo.
echo [2/4] Installing dependencies ...
%PIP% install --upgrade pip --quiet
%PIP% install -r requirements.txt --quiet
if errorlevel 1 (
    echo.
    echo Retrying through a public mirror ...
    %PIP% install -r requirements.txt --quiet ^
        --index-url https://mirrors.aliyun.com/pypi/simple/ ^
        --trusted-host mirrors.aliyun.com
    if errorlevel 1 goto :fail
)

REM ---- 4. run the test suite (fail fast) ------------------------------
echo.
echo [3/4] Running the test suite ...
%PY% -m pytest tests -q
if errorlevel 1 (
    echo.
    echo WARNING: some tests failed. The build will continue, but please
    echo          review the output above before shipping this build.
    echo.
)

REM ---- 5. build the executable ---------------------------------------
echo.
echo [4/4] Building the executable with PyInstaller ...
%PY% build_shopadmin.py --clean
if errorlevel 1 goto :fail

echo.
echo =====================================================================
echo   DONE
echo.
echo   Executable: dist\ShopAdmin\ShopAdmin.exe
echo.
echo   Copy the whole "dist\ShopAdmin" folder to the target computer.
echo   Python does NOT need to be installed there.
echo =====================================================================
echo.
pause
exit /b 0

:fail
echo.
echo =====================================================================
echo   BUILD FAILED - see the messages above.
echo =====================================================================
echo.
pause
exit /b 1
