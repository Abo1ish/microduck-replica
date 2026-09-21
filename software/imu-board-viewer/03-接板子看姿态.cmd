@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
if not exist "%~dp0tools\servo-web-imu\.venv\Scripts\python.exe" (
  echo Run first-time setup before starting the viewer.
  pause
  exit /b 1
)
"%~dp0tools\servo-web-imu\.venv\Scripts\python.exe" "%~dp0tools\servo-web-imu\launcher.py" %*
if errorlevel 1 (
  echo Launch failed. See the error above.
  pause
  exit /b 1
)
