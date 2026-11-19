# Sidekick: one key for AI help in any Windows app

Select text in **any** app, press **Ctrl+Shift+Space**, and the answer
appears in a small window right there. Click **Paste back** to put it into
your app. No browser tab, no other window to operate.

You choose which AI answers, and you can switch at any time (for example
if prices change):

- **Claude Code**, with your Claude plan: no API key, no extra bill
  ("Claude CLI mode", **switched on by default**)
- **Google Gemini**: has a small free tier
- **Ollama**: a free AI running on your own PC (private, works offline)
- **the Claude API**: pay per use
- **any other OpenAI-compatible service** (OpenAI, DeepSeek, Groq, Mistral,
  OpenRouter, LM Studio, ...)

![Sidekick's main window and an answer](docs/sidekick-preview.png)

*Pictures from a test run. On Windows the buttons and borders look like
normal Windows ones.*

## How it works

```text
 1. Select text in
    any app
          |
          v
 2. Press
    Ctrl+Shift+Space
          |
          v
 3. Sidekick copies
    your selection and
    asks "Help with
    this" right away
          |
          v
 4. The answer appears
    in a small window.
    Copy it, click
    Paste back, or ask
    a follow-up.
```

With nothing selected, the hotkey just opens the window, so you can type a
question.

## Which AI should I use?

**Claude Code** (the default)
- Cost: included in a paid Claude plan (Pro or higher). No API key.
- Privacy: your Claude account's privacy settings apply.
- Good to know: text only. Needs Claude Code installed for the terminal.
  Answers count toward your plan's usage limits, which Claude chat and
  Claude Code share (see "Billing with Claude Code" below).

**Claude API**
- Cost: pay per use. Haiku 5.5 is about 0.04 cents a question; Opus 5.5
  about 2 cents.
- Privacy: not used for training by default.
- Good to know: the best answers. Pictures and PDFs work.

**Google Gemini**
- Cost: free tier, about 500 questions a day with gemini-3.5-flash-lite
  and about 20 with gemini-3.8-flash (late 2026).
- Privacy: **on the free tier Google may use what you send to improve its
  products, and people may read it.** Don't send private or
  work-confidential text.

**Ollama**
- Cost: free.
- Privacy: everything stays on your PC.
- Good to know: needs a fairly strong PC (8 to 16 GB of memory). Answers
  are simpler than the big online AIs.

**Other service**
- Cost and privacy: that service's own.
- Good to know: type in its address, key and model.

Free limits and prices change often, so check each service's own page.

Sidekick can also skip its own window and **open the question in the
Claude app or on claude.ai** instead (Settings > General > Send questions
to). That always uses your Claude plan, and you press Enter there.

## What you need

- Windows 10 or 11.
- Python 3.12 or 3.13 (free, from python.org).
- One of the AI services above.

## Install (about 10 minutes, only once)

Have Claude Code in VS Code? Paste the prompt from
[INSTALL-WITH-CLAUDE-CODE.md](INSTALL-WITH-CLAUDE-CODE.md) into its chat.
It installs Sidekick with Claude Code (your Claude plan) for you, asking
before each step.

**1. Install Python.** Open https://www.python.org/downloads/windows/ and
download the "Windows installer (64-bit)" for Python 3.12 or 3.13. Run it,
tick **"Add python.exe to PATH"**, and click **Install Now**.

**2. Get the Sidekick folder.** On GitHub, open this repository, switch to
the branch that has Sidekick in it, click **Code > Download ZIP**, unzip
it, and open the `claude-sidekick` folder inside.

**3. Set it up.** Double-click **`1-Setup.bat`** and wait until it says
**Done!** If Windows says "Windows protected your PC", click **More info**,
then **Run anyway** (only for files you trust).

**4. Start Sidekick.** Double-click **`2-Start-Sidekick.bat`**.

**5. Set up Claude Code.** Claude CLI mode is on from the start: answers
appear inside Sidekick, from Claude Code with your Claude plan. Install
and sign in to Claude Code as shown below ("Claude Code (your Claude
plan)"). To use a different AI instead, open **Settings > AI service**,
pick it, follow its steps below, and click **Save**.

**6. Optional: start it automatically.** Double-click
**`3-Start-With-Windows.bat`**.

**Updating to a new version.** If Sidekick was downloaded with Git (the
install guide does this), double-click **`4-Update-Sidekick.bat`**. It
stops Sidekick, downloads the newest version, updates the libraries only
when they changed, and starts Sidekick again, usually in a few seconds.
Your settings stay as they are. For a quicker start, right-click it and
choose **Send to > Desktop (create shortcut)**. If you downloaded a ZIP
instead, install once with the install guide; after that, updates take
one double-click.

### Setting up each AI service

**Claude Code (your Claude plan):**
1. The Claude Code inside VS Code can't be used by other apps, so install
   it for the terminal. Open PowerShell and run:
   ```text
   irm https://claude.ai/install.ps1 | iex
   ```
2. Open a new terminal, type `claude`, press Enter, and sign in with your
   Claude account in the browser. Then type `/status` and check that it
   shows your Claude plan, not an API key.
3. Restart Sidekick.

### Billing with Claude Code

According to Anthropic's help pages (November 2026):

- **Your plan's limits.** `claude -p` (the mode Sidekick uses) draws from
  your plan's usage limits: a 5-hour limit and weekly limits, shared with
  Claude chat and with Claude Code in VS Code.
- **No surprise bill.** When you reach a limit, answers stop until it
  resets. You are charged extra only if you turned on **usage credits**
  (extra usage) in Claude's settings, and you can set a monthly cap there.
- **API keys win.** If an `ANTHROPIC_API_KEY` is set on your PC, Claude
  Code always uses it in this mode and bills it per use, even when you
  are signed in. Sidekick removes it (and similar settings) whenever it runs
  Claude Code, so your plan is used.
- **Make your limits last.** In Settings, choose the model `haiku` (or
  `sonnet`) for Claude Code, and keep the bigger model for your coding.
- **Kept apart from your coding setup.** Sidekick runs Claude Code in its
  safe mode, with all tools switched off, in an empty folder of its own.
  Your CLAUDE.md files, hooks, plugins, skills, MCP servers and auto memory
  are not loaded, so they don't change Sidekick's answers or use up tokens.
  Sign-in works as usual.

**Google Gemini:**
1. Get a free API key in Google AI Studio (aistudio.google.com).
2. In Sidekick's Settings, paste it next to **Gemini API key** and click
   **Save key**.

**Ollama:**
1. Install Ollama from https://ollama.com/download.
2. In a terminal, download a model once:
   ```text
   ollama pull gemma4:e4b
   ```
   On a PC with 8 GB of memory, use `gemma4:e2b` instead, and type that name in Settings.

**Claude API:** create a key at https://platform.claude.com/settings/keys,
then paste it in Settings. Choose `claude-haiku-5-5` as the model if you
want it cheap.

**Another service:** find its "base URL" and a model name in its
documentation, for example `https://api.openai.com/v1`, then fill in
**Address**, **Model** and the API key.

## Everyday use

- **Select, press the hotkey, read the answer.** It starts with "Help with
  this": Sidekick works out whether to answer, explain an error,
  translate, or explain simply. To make it always do one thing (Explain,
  Fix, Summarize, Improve writing, Draft reply), change "The hotkey asks" in
  Settings.
- **Paste back** puts the answer into your app, replacing the selection.
  **Copy answer** just copies it.
- **Try another action:** click **Explain**, **Fix**, **Summarize**,
  **Improve writing** or **Draft reply** in the window.
- **Follow-up questions:** type them in the window and press Enter.
- **Screen snips:** press Win+Shift+S, drag over an area, then press the
  hotkey. The picture is sent with the question. Claude Code can't read
  pictures, so with Claude Code Sidekick keeps the picture and says so;
  the Claude app and the other services can read them (if the model
  supports it).
- **Files:** click **Attach file...** (PDF, picture or text file).
- **Stop:** click **Stop** at any time. **Esc** closes the window.

## What Sidekick does with your keyboard and clipboard

- **Copying for you.** After you let go of the hotkey, Sidekick presses
  **Ctrl+Insert** (the classic copy key) in your app. Only if the app
  ignores it does Sidekick press **Ctrl+C**.
- **Terminals:** Sidekick never presses Ctrl+C there, because it would
  stop the running program.
- **Private windows:** Sidekick never presses anything in password
  managers, bank sites, private browsing or sign-in screens.
- **Your clipboard** holds the copied selection afterwards, just as if you
  had pressed Ctrl+C. Windows' clipboard history (Win+V) still has what
  you copied before.
- **Paste back** brings your app to the front and presses **Ctrl+V**
  (**Shift+Insert** in terminals). If your app does not come to the front,
  Sidekick doesn't paste anywhere: the answer stays copied for you.
- To switch all of this off, untick "One key" in Settings. The hotkey then
  only opens the window, and you copy text yourself.

## What is sent, and to whom

- Only these are sent: your selection or the text in the box, your
  question, a picture or file you add, and the name of the app and window
  you were in. You can switch the window name off in Settings.
- They go only to the AI service you picked. With Ollama, nothing leaves
  your PC.
- Sidekick asks before sending something that looks like a password, an
  API key or a card number.
- API keys are kept in Windows Credential Manager, not in a file. Your
  questions and answers are not saved on your PC.

## Costs

- **Prices you can change.** Settings > AI service has a price box for each
  service ($ per million tokens). Sidekick uses those prices to estimate
  costs, so the estimates stay right when prices change.
- **Built-in Claude prices.** Sidekick knows the Claude API prices as of
  November 2026. Without your own prices, Ollama and Gemini count as free.
- **Daily limit.** Sidekick stops paid questions when today's estimated
  spending reaches your limit ($2 to start with; 0 means no limit).
  Claude Code, and services without prices, keep working.
- **Big requests.** Before sending a long PDF to the Claude API, Sidekick
  shows the cost and asks first.

## Settings

**General tab:**
- where questions go (answers inside Sidekick, the Claude app, or Chrome)
- one-key mode, and what the hotkey asks
- the hotkey itself
- whether the window name is sent
- your private words

**AI service tab:**
- the service, its model, and its key or address
- your prices and the daily limit

Settings are saved in `%APPDATA%\Sidekick\config.json`. Problems (never
your questions) are logged to `%APPDATA%\Sidekick\sidekick.log`.

## Good to know about the hotkey

- While Sidekick runs, Ctrl+Shift+Space belongs to Sidekick. In Word that
  key normally types a non-breaking space, and in Excel it selects the
  whole sheet. If you need those, choose another hotkey in Settings.
- If another program already uses Ctrl+Shift+Space, Sidekick switches to
  Ctrl+Alt+Shift+Space and tells you in its window.
- If no hotkey works, click **Ask now** in the Sidekick window.

## If something goes wrong

- **"Claude Code was not found":** install it for the terminal (see
  above) and sign in. Then ask again: no restart needed.
- **"You changed the AI service":** click **New question**. Answers from
  one AI service can't be continued by another.
- **"Claude Code is not signed in":** open a terminal, run `claude`, and
  sign in.
- **"Gemini's free limit is used up":** wait (the daily limit resets at
  midnight US Pacific time), or switch model or service in Settings.
- **"Ollama is not running":** start the Ollama app.
- **"The model ... is not installed in Ollama":** run the `ollama pull`
  command shown.
- **Nothing was copied when I pressed the hotkey:** some apps ignore
  copy keys sent by other programs, and apps running "as administrator"
  can't be reached. Press Ctrl+C yourself, then the hotkey.
- **"Python was not found" or "missing tcl/tk":** reinstall Python
  (step 1), ticking "tcl/tk and IDLE", then run `1-Setup.bat` again.
- **Anything else:** the details are in `%APPDATA%\Sidekick\sidekick.log`.

## Other free helpers from Anthropic

These use your Claude plan too:

- **Claude in Chrome** (browser extension, paid plans): works on the web
  page you have open.
- **Claude for Excel, Word and PowerPoint** (Office add-ins, paid plans):
  works directly in your document.

## For developers

```text
sidekick/
  app.py               main window; hotkey, one-key mode, paste back
  popup.py             the answer window
  settings_ui.py       the Settings window (General, AI service)
  services.py          picks the AI service
  claude_code_client.py  Claude Code (claude -p), tools off
  claude_client.py     Claude API (official anthropic library)
  compat_client.py     Gemini, Ollama, other OpenAI-compatible APIs
  handoff.py           opening the Claude app or website
  capture.py           what to pick up from the clipboard
  privacy.py           private windows and secret detection
  attachments.py       pictures, PDFs and text files
  costs.py             cost estimates, your prices, the daily total
  platform_win.py      Windows: hotkey, copy and paste keys, opening apps
tests/                 187 tests
```

Run the tests from the `tests` folder:

```bash
python -m pip install -r ../requirements.txt pytest
python -m pytest -q
```

On Linux, run them with `xvfb-run -a python -m pytest -q`, so the
window tests get a virtual screen.

The tests need no API key and cost nothing: they use fake AI services and
stand-ins for Windows and for the `claude` command. The Windows-only parts
(the hotkey, the copy and paste key presses, the `.bat` files) have not
been run on real Windows yet.
