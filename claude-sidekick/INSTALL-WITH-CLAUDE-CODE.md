# Install Sidekick with Claude Code (VS Code)

Open VS Code on your Windows PC, open the Claude panel, and paste
everything inside the box below. Claude will ask your permission before
each command: read what it says, then approve.

```text
Please install and start "Sidekick" on this Windows PC for me. I am a beginner: before each step, explain in one simple sentence what it does. Ask me before installing any program. If something fails, stop and show me the exact error. Do not change anything outside the folders named below.

What Sidekick is: a small Python app (Tkinter windows) in my public GitHub repo https://github.com/pankajvermak83-ai/redis-user-manager, folder "claude-sidekick", branch "claude/sharp-faraday-hmbw03". By default it opens the Claude desktop app with my question filled in, so it needs no API key.

Use PowerShell for these commands. (If your shell is Git Bash, run each one through: powershell -NoProfile -Command "...")
Folders to use:
- Root: $HOME\SidekickApp
- App:  $HOME\SidekickApp\claude-sidekick

STEP 1 - Check Python (needs 3.10 or newer, with Tkinter):
  py -3 -c "import sys, tkinter; print(sys.version)"
If "py" is not found, try: python -c "import sys, tkinter; print(sys.version)"
If Python is missing or older than 3.10, ask me, then install it:
  winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
Then reload PATH in this session and check again:
  $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
If only "import tkinter" fails: tell me to run the Python installer again, choose Modify, and tick "tcl/tk and IDLE".

STEP 2 - Get the code (or update it if it is already there):
  if (Test-Path "$HOME\SidekickApp\.git") { git -C "$HOME\SidekickApp" pull } else { git clone --branch claude/sharp-faraday-hmbw03 --single-branch https://github.com/pankajvermak83-ai/redis-user-manager.git "$HOME\SidekickApp" }
If git is not available: download https://github.com/pankajvermak83-ai/redis-user-manager/archive/refs/heads/claude/sharp-faraday-hmbw03.zip, unzip it into $HOME\SidekickApp, and use the "claude-sidekick" folder inside it as App.
Check that App contains requirements.txt and a folder named "sidekick".

STEP 3 - Make Sidekick's private Python folder (.venv) and install its 3 libraries (anthropic, pillow, keyring):
  Set-Location "$HOME\SidekickApp\claude-sidekick"
  py -3 -m venv .venv
  .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
  .\.venv\Scripts\python.exe -c "import tkinter, anthropic, PIL, keyring, sidekick.app; print('Sidekick is ready')"
(Use the same Python command that worked in step 1 instead of "py -3" if needed.)
Do not run the .bat files from your shell: some of them wait for a key press. These commands do the same job.

STEP 4 - Check the Claude desktop app (Sidekick opens it with claude:// links):
  Test-Path 'Registry::HKEY_CLASSES_ROOT\claude'
If this prints False: tell me to install the Claude app from https://claude.com/download and sign in, and wait until I say it is done. (Or I can choose "The Claude website in Chrome" later in Sidekick's Settings.)
Then test the link that Sidekick uses:
  Start-Process 'claude://claude.ai/new?q=Hello%20from%20Sidekick%20setup'
Ask me whether Claude opened with "Hello from Sidekick setup" in the question box. It should be filled in but NOT sent.

STEP 5 - Start Sidekick:
  Start-Process -FilePath "$HOME\SidekickApp\claude-sidekick\.venv\Scripts\pythonw.exe" -ArgumentList '-m','sidekick' -WorkingDirectory "$HOME\SidekickApp\claude-sidekick"
Wait 5 seconds, then check that it is running and look for errors:
  Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object CommandLine -like '*sidekick*' | Select-Object ProcessId, CommandLine
  if (Test-Path "$env:APPDATA\Sidekick\sidekick.log") { Get-Content "$env:APPDATA\Sidekick\sidekick.log" -Tail 20 }
Ask me whether the "Sidekick is running" window appeared.

STEP 6 - Let me try it. Tell me to: copy some text (Ctrl+C) in any app, press Ctrl+Shift+Space, click "Explain", and tell you whether Claude opened with the text filled in. If the hotkey does nothing, ask me what Sidekick's main window says next to "Hotkey".

STEP 7 (optional, ask me first) - Start Sidekick automatically when I sign in to Windows:
  $ws = New-Object -ComObject WScript.Shell
  $lnk = $ws.CreateShortcut([Environment]::GetFolderPath('Startup') + '\Sidekick.lnk')
  $lnk.TargetPath = "$HOME\SidekickApp\claude-sidekick\.venv\Scripts\pythonw.exe"
  $lnk.Arguments = '-m sidekick'
  $lnk.WorkingDirectory = "$HOME\SidekickApp\claude-sidekick"
  $lnk.Save()
(To undo later: press Win+R, type shell:startup, and delete Sidekick.lnk.)

STEP 8 (optional, ask me first) - Run Sidekick's 121 automated tests on this PC. Warn me first that small test windows will flash on screen and my clipboard will be overwritten:
  Set-Location "$HOME\SidekickApp\claude-sidekick"
  .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check pytest
  Set-Location tests
  ..\.venv\Scripts\python.exe -m pytest -q
If any test fails, show me the failure output.

At the end, give me a short summary: what was installed and where, which checks passed, and how to use Sidekick every day (copy or snip, press Ctrl+Shift+Space, click a button, press Enter in Claude).
```
