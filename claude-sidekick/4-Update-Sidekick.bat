@echo off
setlocal
cd /d "%~dp0"
title Update Sidekick
echo.
echo  Updating Sidekick...
echo.

if not exist ".venv\Scripts\pythonw.exe" (
  echo  Sidekick is not set up yet. Double-click 1-Setup.bat first.
  echo.
  pause
  exit /b 1
)
where git >nul 2>nul
if errorlevel 1 (
  echo  Git was not found, so Sidekick cannot download its updates.
  echo  Install Git from https://git-scm.com/download/win and try again,
  echo  or install Sidekick again with the install guide.
  echo.
  pause
  exit /b 1
)
git -C .. rev-parse --git-dir >nul 2>nul
if errorlevel 1 (
  echo  This copy of Sidekick was not downloaded with Git, so it cannot update itself.
  echo  Install it again once with the install guide, INSTALL-WITH-CLAUDE-CODE.md.
  echo.
  pause
  exit /b 1
)

rem Stop Sidekick, so its files can be replaced.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*sidekick*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
timeout /t 1 /nobreak >nul 2>nul

set "OLD="
for /f %%i in ('git -C .. rev-parse HEAD') do set "OLD=%%i"
echo  Downloading the newest version...
git -C .. pull --ff-only -q
if errorlevel 1 (
  echo.
  echo  The update could not be downloaded. The messages above say why.
  echo  Sidekick starts again with the version you had.
  start "" ".venv\Scripts\pythonw.exe" -m sidekick
  echo.
  pause
  exit /b 1
)
set "NEW="
for /f %%i in ('git -C .. rev-parse HEAD') do set "NEW=%%i"

rem Install libraries only when the list of libraries has changed.
fc /b requirements.txt .venv\requirements-installed.txt >nul 2>nul
if errorlevel 1 (
  echo  Updating the libraries Sidekick uses...
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
  if errorlevel 1 goto failed
  copy /y requirements.txt .venv\requirements-installed.txt >nul
)

rem Check that the new version loads before starting it.
".venv\Scripts\python.exe" -c "import sidekick.app"
if errorlevel 1 goto failed

echo.
if "%OLD%"=="%NEW%" (
  echo  Sidekick is already up to date.
) else (
  echo  Updated. What is new:
  git -C .. log --oneline --no-decorate %OLD%..%NEW%
)
start "" ".venv\Scripts\pythonw.exe" -m sidekick
echo.
echo  Sidekick is running again. This window closes by itself.
timeout /t 8 >nul 2>nul
exit /b 0

:failed
echo.
echo  Something went wrong while updating. The messages above say what.
echo  Check your internet connection and try again, or install Sidekick
echo  again with the install guide.
echo.
pause
exit /b 1
