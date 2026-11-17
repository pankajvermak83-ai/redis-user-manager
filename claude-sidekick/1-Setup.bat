@echo off
setlocal
cd /d "%~dp0"
title Sidekick setup
echo.
echo  Setting up Sidekick. This takes a minute or two.
echo.

set "PY="
py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY (
  echo  Python was not found on this computer.
  echo  Install it from https://www.python.org/downloads/windows/
  echo  then double-click 1-Setup.bat again.
  echo.
  pause
  exit /b 1
)

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo  Your Python is too old. Sidekick needs Python 3.10 or newer.
  echo  Install a newer one from https://www.python.org/downloads/windows/
  echo.
  pause
  exit /b 1
)

%PY% -c "import tkinter" >nul 2>nul
if errorlevel 1 (
  echo  Your Python is missing "tcl/tk", which Sidekick needs for its windows.
  echo  Run the Python installer again, choose Modify, and tick "tcl/tk and IDLE".
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo  Making a private Python folder for Sidekick...
  %PY% -m venv .venv
  if errorlevel 1 goto failed
)

echo  Downloading and installing the libraries Sidekick uses...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto failed

echo.
echo  Done! Now double-click 2-Start-Sidekick.bat
echo.
pause
exit /b 0

:failed
echo.
echo  Something went wrong. The messages above say what.
echo  Check your internet connection, then run 1-Setup.bat again.
echo.
pause
exit /b 1
