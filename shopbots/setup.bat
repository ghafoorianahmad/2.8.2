@echo off
rem Double-click launcher for the shopbots one-time setup on Windows.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
echo.
pause
