# Install Sidekick with Claude in VS Code

**You need:** a Windows 10 or 11 PC, VS Code with the Claude extension
(signed in), and a paid Claude plan (Pro or Max). It takes about 15 minutes.

Open VS Code, open the Claude panel, and paste everything inside the box
below. Claude asks your permission before each command: read what it
says, then approve. The same steps also update an older copy of Sidekick.

```text
Please install (or update) "Sidekick" on this Windows PC and set it up to answer with Claude Code using my Claude plan ("Claude CLI mode"). I am a beginner: before each step, explain in one simple sentence what it does. Ask me before installing any program. If something fails, stop and show me the exact error. Never ask me to paste an API key into this chat. Do not change anything outside the folders named below unless a step says so and I agree.

What Sidekick is: a small Python app in my public GitHub repo https://github.com/pankajvermak83-ai/redis-user-manager (folder "claude-sidekick", branch "claude/sharp-faraday-hmbw03"). I select text in any app, press Ctrl+Shift+Space, and the answer appears in Sidekick's small window. Sidekick runs Claude Code ("claude -p") in the background with all its tools switched off, so answers come from my Claude plan with no API bill.

Run every command in PowerShell. If your command tool is Git Bash, run them through PowerShell so that the $ signs and quotes stay exactly as written (for example: save the commands in a .ps1 file in $env:TEMP and run it with powershell -NoProfile -ExecutionPolicy Bypass -File).
Folders:
- Root: $HOME\SidekickApp
- App:  $HOME\SidekickApp\claude-sidekick

STEP 1 - Check Python (3.10 or newer, with Tkinter):
  py -3 -c "import sys, tkinter; print(sys.version)"
If "py" is not found, try: python -c "import sys, tkinter; print(sys.version)"
If Python is missing or older than 3.10, ask me, then install it and reload PATH:
  winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
  $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
If only "import tkinter" fails: tell me to run the Python installer again, choose Modify, and tick "tcl/tk and IDLE".

STEP 2 - Get the newest Sidekick (download it, or update it if it is already there):
  git --version
If git is not found, ask me, then install it and reload PATH (same PATH command as in step 1):
  winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
Then:
  if (Test-Path "$HOME\SidekickApp\.git") { git -C "$HOME\SidekickApp" pull } else { git clone --branch claude/sharp-faraday-hmbw03 --single-branch https://github.com/pankajvermak83-ai/redis-user-manager.git "$HOME\SidekickApp" }
If $HOME\SidekickApp already exists but has no .git folder (an older ZIP download), ask me, then rename it to SidekickApp-old and run the command again.
Check that this file exists: $HOME\SidekickApp\claude-sidekick\sidekick\claude_code_client.py

STEP 3 - Stop an older Sidekick if one is running, then make Sidekick's private Python folder (.venv) and install its 3 libraries:
  Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object CommandLine -like '*sidekick*' | ForEach-Object { Stop-Process -Id $_.ProcessId }
  Set-Location "$HOME\SidekickApp\claude-sidekick"
  py -3 -m venv .venv
  .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
  .\.venv\Scripts\python.exe -c "import tkinter, anthropic, PIL, keyring, sidekick.app; print('Sidekick is ready')"
(Use the Python command that worked in step 1 instead of "py -3" if needed. Don't run the .bat files from your shell: some of them wait for a key press.)

STEP 4 - Claude Code for the terminal. (The Claude Code inside VS Code is built into the extension, and other apps can't use it.)
  claude --version
If it is not found, ask me, then install it with Anthropic's official installer, reload PATH (same command as in step 1), and check again:
  irm https://claude.ai/install.ps1 | iex
  claude --version
If "claude" is still not found, use its full path, & "$HOME\.local\bin\claude.exe", in the commands below. Sidekick finds it there by itself.

STEP 5 - Make sure Claude Code uses my plan, not per-use API billing:
  [Environment]::GetEnvironmentVariable('ANTHROPIC_API_KEY','User'); [Environment]::GetEnvironmentVariable('ANTHROPIC_API_KEY','Machine'); $env:ANTHROPIC_API_KEY
If any of these prints a key, tell me (show only its first 8 characters). Sidekick removes it when it runs Claude Code, but my own terminal would still use it, so ask me whether to remove it.
Then test Claude Code:
  'Reply with just the word OK' | claude -p --max-turns 1
If it prints OK, go on. If it says I need to log in: tell me to open a new PowerShell window (Start menu, type PowerShell), type claude, press Enter, sign in with my Claude account, then type /exit. Wait until I say it is done, then run the test again.
Then ask me to check one thing myself: in a PowerShell window, type claude, press Enter, type /status, and check that it shows my Claude plan (Pro or Max), not an API key or a Console account. Then /exit.
Remind me: to never be charged beyond my plan, keep "usage credits" (extra usage) off in my Claude account settings.

STEP 6 - Ask me which model Sidekick should use: haiku (fastest, uses the least of my plan's limits) or sonnet (smarter, uses more). Use haiku if I don't mind. Then save Sidekick's settings (this keeps any other settings already there). Note: 'api' below is only Sidekick's name for "answer inside Sidekick"; with Claude Code there is no API bill.
  $cfg = "$env:APPDATA\Sidekick\config.json"
  New-Item -ItemType Directory -Force -Path (Split-Path $cfg) | Out-Null
  $data = @{}
  if (Test-Path $cfg) { (Get-Content $cfg -Raw | ConvertFrom-Json).psobject.Properties | ForEach-Object { $data[$_.Name] = $_.Value } }
  $data['send_to'] = 'api'
  $data['provider'] = 'claude_code'
  $data['claude_code_model'] = 'haiku'
  $data['instant'] = $true
  $data['hotkey_action'] = 'smart'
  $data | ConvertTo-Json -Depth 5 | Set-Content -Path $cfg -Encoding UTF8
(Use 'sonnet' instead of 'haiku' if I chose it.)

STEP 7 - Start Sidekick (stop an old copy first, so it reads the new settings):
  Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object CommandLine -like '*sidekick*' | ForEach-Object { Stop-Process -Id $_.ProcessId }
  Start-Process -FilePath "$HOME\SidekickApp\claude-sidekick\.venv\Scripts\pythonw.exe" -ArgumentList '-m','sidekick' -WorkingDirectory "$HOME\SidekickApp\claude-sidekick"
Wait 5 seconds, then check that it is running and look for errors:
  Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object CommandLine -like '*sidekick*' | Select-Object ProcessId, CommandLine
  if (Test-Path "$env:APPDATA\Sidekick\sidekick.log") { Get-Content "$env:APPDATA\Sidekick\sidekick.log" -Tail 20 }
Ask me whether the "Sidekick is running" window appeared, and what it says next to "Hotkey".

STEP 8 - Let me try it. Tell me to:
  1. Open Notepad, type a sentence with a few spelling mistakes, and select it.
  2. Press Ctrl+Shift+Space. Sidekick's small window should open and show an answer within a few seconds.
  3. Click "Fix" in that window and wait for the new answer. Then click "Paste back": the answer should replace the selected sentence in Notepad.
Ask me what happened. If the hotkey does nothing, ask me what Sidekick's main window says next to "Hotkey". If the answer shows [Problem], read its text with me and help me fix it.

STEP 9 (optional, ask me first) - Shortcuts:
  a) In the Start menu, so I can start Sidekick by pressing the Windows key and typing Sidekick.
  b) In Startup, so Sidekick starts by itself when I sign in to Windows.
For each one I want, set $folder = [Environment]::GetFolderPath('Programs') for a), or [Environment]::GetFolderPath('Startup') for b), then run:
  $ws = New-Object -ComObject WScript.Shell
  $lnk = $ws.CreateShortcut("$folder\Sidekick.lnk")
  $lnk.TargetPath = "$HOME\SidekickApp\claude-sidekick\.venv\Scripts\pythonw.exe"
  $lnk.Arguments = '-m sidekick'
  $lnk.WorkingDirectory = "$HOME\SidekickApp\claude-sidekick"
  $lnk.Save()
(To undo later: press Win+R, type shell:programs or shell:startup, and delete Sidekick.lnk there.)

STEP 10 (optional, ask me first) - Run Sidekick's automatic tests on this PC. Warn me first that small test windows will flash on screen for about a minute and my clipboard will be overwritten:
  Set-Location "$HOME\SidekickApp\claude-sidekick"
  .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check pytest
  Set-Location tests
  ..\.venv\Scripts\python.exe -m pytest -q
If any test fails, show me the failure output.

At the end, give me a short summary: what was installed and where, which checks passed, and how to use Sidekick every day (select text, press Ctrl+Shift+Space, read the answer, then click Paste back or Copy answer).
```

## Want a different AI?

After installing, open Sidekick's **Settings**, then the **AI service**
tab. You can switch to Google Gemini, Ollama (free, on your PC), the
Claude API, or another service. The README explains each one.
