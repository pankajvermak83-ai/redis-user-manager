@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo  Sidekick is not set up yet. Double-click 1-Setup.bat first.
  echo.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m sidekick
