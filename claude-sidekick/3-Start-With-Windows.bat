@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo  Sidekick is not set up yet. Double-click 1-Setup.bat first.
  echo.
  pause
  exit /b 1
)
set "SIDEKICK_PYTHONW=%~dp0.venv\Scripts\pythonw.exe"
set "SIDEKICK_FOLDER=%~dp0"
powershell -NoProfile -Command "$link = [Environment]::GetFolderPath('Startup') + '\Sidekick.lnk'; $s = (New-Object -ComObject WScript.Shell).CreateShortcut($link); $s.TargetPath = $env:SIDEKICK_PYTHONW; $s.Arguments = '-m sidekick'; $s.WorkingDirectory = $env:SIDEKICK_FOLDER; $s.Description = 'Sidekick: ask Claude from any app'; $s.Save()"
if errorlevel 1 (
  echo  Sorry, Sidekick could not be added to startup.
  echo.
  pause
  exit /b 1
)
echo.
echo  Done. Sidekick will now start by itself when you sign in to Windows.
echo.
echo  To undo this later: press Win+R, type  shell:startup  and press Enter,
echo  then delete the file called Sidekick.
echo.
pause
