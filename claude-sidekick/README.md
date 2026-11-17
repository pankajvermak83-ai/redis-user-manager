# Sidekick: ask Claude from any Windows app

Sidekick is a small helper for Windows. Copy something in **any** app,
press **Ctrl+Shift+Space**, and ask Claude about it. The answer appears in
a small window, ready to copy back into your work.

It works the same in Excel, Word, Outlook, your browser, PDFs, error
messages, chat apps: anything you can copy text from or take a snip of.

![Sidekick's main window and Ask window](docs/sidekick-preview.png)

*Picture from a test run with a scripted answer. On Windows the buttons
and borders look like normal Windows ones.*

## How it works

```text
 1. Copy something
    (Ctrl+C), or snip
    the screen
    (Win+Shift+S)
          |
          v
 2. Press
    Ctrl+Shift+Space
          |
          v
 3. Sidekick shows what
    it WILL send. Nothing
    has left your PC yet.
          |
          v
 4. Type a question and
    click Ask. Only now
    is it sent to Claude.
          |
          v
 5. The answer appears.
    Click "Copy answer",
    then Ctrl+V in your
    app.
```

## What you need

- Windows 10 or 11.
- Python 3.12 or 3.13 (free, from python.org).
- An Anthropic API key with some credit. The API is pay-as-you-go
  (a typical question costs about 1-2 US cents) and is billed separately
  from a Claude Pro or Max subscription. Claude Max, Ultra and Team plans
  include monthly API credits that you can claim in the Anthropic Console.

## Install (about 10 minutes, only once)

**1. Install Python**

1. Open https://www.python.org/downloads/windows/ and download the
   "Windows installer (64-bit)" for Python 3.12 or 3.13.
2. Run it. Tick **"Add python.exe to PATH"**, then click **Install Now**.

**2. Get the Sidekick folder**

1. On GitHub, open this repository and switch to the branch that has
   Sidekick in it.
2. Click **Code**, then **Download ZIP**, and unzip it.
3. Open the `claude-sidekick` folder inside.

**3. Set it up**

Double-click **`1-Setup.bat`** and wait until it says **Done!**

If Windows says "Windows protected your PC", click **More info**, then
**Run anyway**. Only do this for files you trust.

**4. Get your API key**

1. Sign in at https://platform.claude.com/settings/keys
2. Click **Create key**, give it a name such as "Sidekick", and copy it.
   The key is shown only once.
3. Add credit at https://platform.claude.com/settings/billing
   (**Buy credits**). $5 is roughly 250 questions with the default model.

**5. Start Sidekick**

1. Double-click **`2-Start-Sidekick.bat`**. The Sidekick window opens.
2. Click **Settings**, paste your key, and click **Save key**.

**6. Optional: start it automatically**

Double-click **`3-Start-With-Windows.bat`** and Sidekick will start by
itself every time you sign in to Windows.

## Everyday use

- **Ask about text:** select it, press Ctrl+C, press Ctrl+Shift+Space,
  type your question, and press Enter.
- **One-click help:** instead of typing, click **Explain**, **Fix**,
  **Summarize**, **Improve writing** or **Draft reply**.
- **Ask about something on screen:** press Win+Shift+S, drag over the
  area, then press Ctrl+Shift+Space.
- **Ask about a file:** in the Sidekick window click **Attach file...**
  (PDF, picture or text file). For Word or Excel files, copy the part you
  need, or save the file as PDF first.
- **Keep going:** type a follow-up question in the same window. Claude
  remembers the conversation until you click **New question** or close it.
- **Use the answer:** click **Copy answer**, go back to your app, and
  press Ctrl+V.
- **Changed your mind:** click **Stop** at any time.

## What is sent, and what is not

- **Nothing is sent until you click Ask** (or a one-click button). Before
  that, you can edit or delete everything in the box.
- Only these are sent: your question, the text in the box, a picture or
  file you attached, and the name of the app and window you were in.
  You can switch the window name off in Settings.
- Sidekick never watches your screen or your typing by itself, and never
  clicks or types in your apps. It only looks at what you copied, and only
  if you copied it in the last 2 minutes.
- **Private windows are skipped.** In password managers, banking sites,
  private browsing and sign-in screens, Sidekick reads nothing and does
  not send the window name. You can add your own words in Settings.
- If a password manager marks a copy as private, Sidekick ignores it.
- If the text looks like it contains a password, an API key or a card
  number, Sidekick asks before sending it.
- Your API key is kept in Windows Credential Manager, not in a file.
  Your questions and answers are not saved on your PC.

## Costs

The prices below are estimates for a question about 3,000 tokens long
(roughly four pages of copied text) with a short answer, using Anthropic's
prices in November 2026:

- **Claude Opus 5.5** (the default, smartest): about 2 cents, a little more
  when it thinks hard.
- **Claude Sonnet 5.5** (faster): about 1 cent.
- **Claude Haiku 5.5** (fastest): well under 0.1 cent.

Built-in limits:

- **Daily limit:** Sidekick stops sending when today's estimated spending
  reaches **$2**. Change this in Settings (0 means no limit).
- **Big requests:** before sending a long PDF or file that would cost more
  than 25 cents, Sidekick shows the cost and asks first.

Sidekick's numbers are estimates. The real ones are on the Usage page of
the Anthropic Console.

## Settings

Click **Settings** in the Sidekick window to change:

- the Claude model (Opus 5.5, Sonnet 5.5 or Haiku 5.5),
- how hard Claude thinks (low, medium or high),
- the hotkey,
- the daily limit,
- whether the app and window name are sent,
- the list of "private words".

Sidekick keeps its settings in `%APPDATA%\Sidekick\config.json` and writes
problems (never your questions) to `%APPDATA%\Sidekick\sidekick.log`.

## Good to know about the hotkey

- While Sidekick runs, Ctrl+Shift+Space belongs to Sidekick. In Word that
  key normally types a non-breaking space, and in Excel it selects the
  whole sheet. If you need those, choose another hotkey in Settings.
- If another program already uses Ctrl+Shift+Space, Sidekick switches to
  Ctrl+Alt+Shift+Space and tells you in its window.
- If no hotkey works, click **Ask now** in the Sidekick window instead.

## If something goes wrong

- **"Python was not found":** install Python (step 1), then run
  `1-Setup.bat` again.
- **"Missing tcl/tk":** run the Python installer again, choose **Modify**,
  tick **tcl/tk and IDLE**, then run `1-Setup.bat` again.
- **The hotkey does nothing:** look at the Sidekick window. It says which
  hotkey is active. Try **Ask now**, or pick another hotkey in Settings.
- **"Your API key was not accepted":** create a new key and paste it in
  Settings.
- **"No credit left":** add credit at platform.claude.com/settings/billing.
- **"Sidekick is already running":** look for it on the taskbar.
- **Anything else:** the details are in `%APPDATA%\Sidekick\sidekick.log`.

## For developers

```text
sidekick/
  app.py           main window, wires everything together
  popup.py         the Ask window
  settings_ui.py   the Settings window
  claude_client.py talks to Claude (official anthropic library)
  capture.py       decides what to pick up from the clipboard
  privacy.py       private windows and secret detection
  attachments.py   pictures, PDFs and text files
  costs.py         cost estimates and the daily total
  platform_win.py  Windows hotkey, window name, clipboard checks
tests/             94 tests
```

Run the tests from the `tests` folder:

```bash
python -m pip install -r ../requirements.txt pytest
python -m pytest -q
```

On Linux, run them with `xvfb-run -a python -m pytest -q`, so the
window tests get a virtual screen.

The tests talk to a fake Claude server on your own computer, so they
need no API key and cost nothing. The Windows-only parts are tested with
stand-ins for Windows, and the `.bat` files have not been run on real
Windows yet.
