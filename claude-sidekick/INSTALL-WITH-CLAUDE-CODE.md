# Install Sidekick with Claude Code (VS Code)

Open VS Code on your Windows PC, open the Claude panel, and paste
everything inside the box below. Claude will ask your permission before
each command: read what it says, then approve.

```text
Please install and start "Sidekick" on this Windows PC for me. I am a beginner: before each step, explain in one simple sentence what it does. Ask me before installing any program. If something fails, stop and show me the exact error. Never ask me to paste an API key into this chat. Do not change anything outside the folders named below.

What Sidekick is: a small Python app (Tkinter windows) in my public GitHub repo https://github.com/pankajvermak83-ai/redis-user-manager, folder "claude-sidekick", branch "claude/sharp-faraday-hmbw03". I select text in any app, press Ctrl+Shift+Space, and the answer appears in Sidekick's small window.

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
If $HOME\SidekickApp already exists but has no .git folder (an older ZIP download), ask me, then rename it to SidekickApp-old and run the command again.
If git is not available: download https://github.com/pankajvermak83-ai/redis-user-manager/archive/refs/heads/claude/sharp-faraday-hmbw03.zip, unzip it into $HOME\SidekickApp, and use the "claude-sidekick" folder inside it as App.
Check that App contains requirements.txt and a folder named "sidekick".

STEP 3 - Make Sidekick's private Python folder (.venv) and install its 3 libraries (anthropic, pillow, keyring).
First stop Sidekick if an older copy is running, so its files can be updated:
  Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object CommandLine -like '*sidekick*' | ForEach-Object { Stop-Process -Id $_.ProcessId }
Then:
  Set-Location "$HOME\SidekickApp\claude-sidekick"
  py -3 -m venv .venv
  .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
  .\.venv\Scripts\python.exe -c "import tkinter, anthropic, PIL, keyring, sidekick.app; print('Sidekick is ready')"
(Use the same Python command that worked in step 1 instead of "py -3" if needed.)
Do not run the .bat files from your shell: some of them wait for a key press. These commands do the same job.

STEP 4 - Ask me which AI should answer, and set it up:
  A) Claude Code with my Claude plan (no API key; needs Claude Pro or higher) - recommended if I have a paid Claude plan
  B) Google Gemini free tier (I will paste my own key into Sidekick's Settings later; Google may use free-tier text)
  C) Ollama: a free AI on this PC (private; needs 8 GB of memory or more)
  D) No answers inside Sidekick: open the question in the Claude desktop app instead

If A:
  The Claude Code inside VS Code can't be used by other apps, so check for the terminal version:
    claude --version
  If it is not found, ask me, then install it (Anthropic's official installer) and reload PATH:
    irm https://claude.ai/install.ps1 | iex
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
  Then tell me to open a new PowerShell window, type claude, press Enter and sign in with my Claude account, then type /status there and check that it shows my Claude plan (not an API key). Wait until I say it is done.
  Check that no API key is set on this PC (one would make Claude Code bill per use instead of using my plan):
    [Environment]::GetEnvironmentVariable('ANTHROPIC_API_KEY','User'); [Environment]::GetEnvironmentVariable('ANTHROPIC_API_KEY','Machine'); $env:ANTHROPIC_API_KEY
  If any of these prints a key, tell me (show only the first 8 characters). Sidekick removes it when it runs Claude Code, but my own terminal would still use it; ask me whether to remove it.
  Then test it:
    'Reply with just the word OK' | claude -p --max-turns 1
  It should print OK. If it says to log in, I am not signed in yet.
  Also tell me: to never be charged beyond my plan, keep "usage credits" (extra usage) off in Claude's settings.

If B:
  Tell me to get a free API key at https://aistudio.google.com (API keys), and that I will paste it into Sidekick's Settings myself after it starts (AI service tab, "Gemini API key", Save key).

If C:
  Check: ollama --version
  If it is not found, ask me, then tell me to install Ollama from https://ollama.com/download and wait until I say it is done.
  Check how much memory this PC has:
    [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
  Use the model gemma4:e4b if it is 16 or more, otherwise gemma4:e2b. Download it (this can take a while):
    ollama pull gemma4:e4b
  Test it:
    ollama run gemma4:e4b "Reply with just the word OK"

If D:
  Check the Claude desktop app is installed: Test-Path 'Registry::HKEY_CLASSES_ROOT\claude'
  If it prints False, tell me to install it from https://claude.com/download and sign in.

STEP 5 - Save Sidekick's settings for my choice (keeps any other settings already there):
  $cfg = "$env:APPDATA\Sidekick\config.json"
  New-Item -ItemType Directory -Force -Path (Split-Path $cfg) | Out-Null
  $data = @{}
  if (Test-Path $cfg) { (Get-Content $cfg -Raw | ConvertFrom-Json).psobject.Properties | ForEach-Object { $data[$_.Name] = $_.Value } }
  $data['instant'] = $true
  $data['hotkey_action'] = 'smart'
  # A:  $data['send_to'] = 'api'; $data['provider'] = 'claude_code'; $data['claude_code_model'] = 'haiku'   (or 'sonnet': ask me; haiku uses the least of my plan's limits)
  # B:  $data['send_to'] = 'api'; $data['provider'] = 'gemini'
  # C:  $data['send_to'] = 'api'; $data['provider'] = 'ollama'; $data['ollama_model'] = 'gemma4:e4b'   (or gemma4:e2b)
  # D:  $data['send_to'] = 'claude_app'
  (run only the line for my choice, without the leading #)
  $data | ConvertTo-Json -Depth 5 | Set-Content -Path $cfg -Encoding UTF8

STEP 6 - Start Sidekick (stop an old copy first, so it reads the new settings):
  Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object CommandLine -like '*sidekick*' | ForEach-Object { Stop-Process -Id $_.ProcessId }
  Start-Process -FilePath "$HOME\SidekickApp\claude-sidekick\.venv\Scripts\pythonw.exe" -ArgumentList '-m','sidekick' -WorkingDirectory "$HOME\SidekickApp\claude-sidekick"
Wait 5 seconds, then check that it is running and look for errors:
  Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object CommandLine -like '*sidekick*' | Select-Object ProcessId, CommandLine
  if (Test-Path "$env:APPDATA\Sidekick\sidekick.log") { Get-Content "$env:APPDATA\Sidekick\sidekick.log" -Tail 20 }
Ask me whether the "Sidekick is running" window appeared. If I chose B, remind me now to open Settings > AI service and save my Gemini key there.

STEP 7 - Let me try it. Tell me to: select a sentence with a few spelling mistakes in any app (for example Notepad), press Ctrl+Shift+Space, and tell you whether the answer appeared in Sidekick's small window. Then tell me to click "Paste back" and check that the corrected text replaced my selection. If the hotkey does nothing, ask me what Sidekick's main window says next to "Hotkey".

STEP 8 (optional, ask me first) - Start Sidekick automatically when I sign in to Windows:
  $ws = New-Object -ComObject WScript.Shell
  $lnk = $ws.CreateShortcut([Environment]::GetFolderPath('Startup') + '\Sidekick.lnk')
  $lnk.TargetPath = "$HOME\SidekickApp\claude-sidekick\.venv\Scripts\pythonw.exe"
  $lnk.Arguments = '-m sidekick'
  $lnk.WorkingDirectory = "$HOME\SidekickApp\claude-sidekick"
  $lnk.Save()
(To undo later: press Win+R, type shell:startup, and delete Sidekick.lnk.)

STEP 9 (optional, ask me first) - Run Sidekick's automated tests on this PC. Warn me first that small test windows will flash on screen and my clipboard will be overwritten:
  Set-Location "$HOME\SidekickApp\claude-sidekick"
  .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check pytest
  Set-Location tests
  ..\.venv\Scripts\python.exe -m pytest -q
If any test fails, show me the failure output.

At the end, give me a short summary: what was installed and where, which AI answers, which checks passed, and how to use Sidekick every day (select text, press Ctrl+Shift+Space, read the answer, click Paste back or Copy answer).
```
