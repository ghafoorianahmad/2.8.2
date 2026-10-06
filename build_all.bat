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
set "SHOP_NOPAUSE=1"

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
pause
exit /b 0

:fail
echo.
echo =====================================================================
echo   BUILD FAILED - see the messages above.
echo =====================================================================
pause
exit /b 1
