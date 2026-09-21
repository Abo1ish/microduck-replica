@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Python environment is missing. Run the first-time setup CMD first.
    pause
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0launcher.py" --demo %*
if errorlevel 1 (
    echo Startup failed. Read the message above or logs\launcher-error.txt.
    pause
    exit /b 1
)
