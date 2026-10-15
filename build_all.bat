@echo off
REM =====================================================================
REM  Full clean build, in the only correct order:
REM    1. shopsystem\build_exe.bat      (shopapi + shopbots tests, ShopSystem.exe)
REM    2. shopadmin tests
REM    3. shopadmin\build_installer.bat (ShopAdmin.exe + ShopAdminSetup.exe)
REM  build_installer.bat strips .env / *.db / *.log from the staging folder
REM  and refuses to continue if any remain.
REM
REM  Usage:  build_all.bat
REM =====================================================================
setlocal
set "ROOT=%~dp0"
REM The caller's SHOP_NOPAUSE (e.g. "set SHOP_NOPAUSE=1" in a scripted run)
REM decides whether THIS script pauses at the end; the sub-scripts never do.
set "CALLER_NOPAUSE=%SHOP_NOPAUSE%"
set "SHOP_NOPAUSE=1"

REM v2.6.2: pytest gets a fresh, writable temp root for this build only. A shared
REM %TEMP%\pytest-of-<user> left with denied access by an earlier run used to stop
REM the build ("PermissionError: Access is denied") although every test was fine.
REM A new folder under %TEMP% (not the shared pytest-of-<user>); pytest makes
REM numbered basetemp dirs inside it and never reuses another run's.
for /f %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMddHHmmss"') do set "BUILD_STAMP=%%t"
set "SHOP_TEST_ROOT=%TEMP%\ShopBuild"
if exist "%SHOP_TEST_ROOT%" (
    for /d %%d in ("%SHOP_TEST_ROOT%\tmp_*") do rd /s /q "%%d" 2>nul
)
set "BUILD_ID=tmp_%BUILD_STAMP%_%RANDOM%"
set "SHOP_TEST_TMP=%SHOP_TEST_ROOT%\%BUILD_ID%"
mkdir "%SHOP_TEST_TMP%" 2>nul
if not exist "%SHOP_TEST_TMP%" set "SHOP_TEST_TMP=%ROOT%.buildtmp\%BUILD_ID%"
if not exist "%SHOP_TEST_TMP%" mkdir "%SHOP_TEST_TMP%" 2>nul
set "TEMP=%SHOP_TEST_TMP%"
set "TMP=%SHOP_TEST_TMP%"
set "PYTEST_ADDOPTS=-p no:cacheprovider"
echo pytest temp: %SHOP_TEST_TMP%

echo.
echo === [1/3] ShopSystem (API + bots) ===================================
call "%ROOT%shopsystem\build_exe.bat"
if errorlevel 1 goto :fail

echo.
echo === [2/3] ShopAdmin tests ===========================================
pushd "%ROOT%shopadmin"
set "QT_QPA_PLATFORM=offscreen"
".venv\Scripts\python.exe" -m pytest tests -q
if errorlevel 1 (
    popd
    echo [ERROR] shopadmin tests FAILED - fix them before building.
    goto :fail
)
set "QT_QPA_PLATFORM="
popd

echo.
echo === [3/3] ShopAdmin + installer =====================================
call "%ROOT%shopadmin\build_installer.bat"
if errorlevel 1 goto :fail

echo.
echo =====================================================================
echo   ALL DONE:  shopadmin\dist\installer\ShopAdminSetup.exe
echo =====================================================================
if not defined CALLER_NOPAUSE pause
exit /b 0

:fail
echo.
echo =====================================================================
echo   BUILD FAILED - see the messages above.
echo =====================================================================
if not defined CALLER_NOPAUSE pause
exit /b 1
