@echo off
rem Double-click launcher for shopbots on Windows.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
echo.
pause
