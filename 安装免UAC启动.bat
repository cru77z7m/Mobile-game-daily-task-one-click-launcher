@echo off
rem ============================================================
rem  Install no-UAC scheduled task + desktop shortcut + MAA guard.
rem  If it says access denied, right-click this file and choose
rem  Run as administrator.
rem ============================================================
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_no_uac.ps1"
echo.
pause
