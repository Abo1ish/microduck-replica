@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
set "setup_result=%errorlevel%"
if not "%setup_result%"=="0" echo Setup failed. Read the error above.
pause
exit /b %setup_result%
