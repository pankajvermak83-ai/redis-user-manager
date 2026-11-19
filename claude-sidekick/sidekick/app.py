"""Sidekick's small main window, and the glue between all the parts."""

from __future__ import annotations

import logging
import logging.handlers
import os
import queue
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from tkinter import font as tkfont

from . import keystore, services
from .capture import Capture, ClipboardWatch, capture_context
from .config import (
    DEFAULT_HOTKEY, FALLBACK_HOTKEY, HOTKEY_ACTIONS, Settings, config_dir, config_path, load_settings,
)
from .costs import DailySpend, format_money
from .handoff import TARGET_NAMES, plan_handoff
from .hotkeys import Hotkey, parse_hotkey
from .platform_base import Platform, WindowInfo, get_platform
from .popup import Dialogs, Popup
from .claude_code_client import NO_PICTURES, find_claude
from .privacy import is_private_window
from .settings_ui import SettingsDialog

log = logging.getLogger(__name__)


class SidekickApp:
    def __init__(
        self,
        root: tk.Tk,
        platform: Platform,
        settings: Settings,
        spend: DailySpend,
        *,
        settings_path: Path | None = None,
        dialogs: Dialogs | None = None,
        client_factory=None,
    ):
        self.root = root
        self.platform = platform
        self.settings = settings
        self.spend = spend
        self.settings_path = settings_path or config_path()
        self.dialogs = dialogs or Dialogs()
        # Makes the client for the chosen AI service (the tests swap in fakes).
        self._client_factory = client_factory or services.make_client
        self._client = None

        self.watch = ClipboardWatch(platform)
        self.hotkey_events: queue.Queue = queue.Queue()  # filled by the hotkey thread
        self.active_hotkey: Hotkey | None = None
        self.hotkey_note = ""
        self.settings_dialog: SettingsDialog | None = None
        self.toast: tk.Toplevel | None = None
        self.toast_text = ""
        self._toast_job = None
        self._closed = False

        root.report_callback_exception = self._on_window_error
        self._build_main_window()
        self.popup = Popup(self)
        self._apply_hotkey()
        self.refresh_main()
        self._tick_job = root.after(150, self._tick)

    # ------------------------------------------------------- main window

    def _build_main_window(self) -> None:
        root = self.root
        root.title("Sidekick")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        bold = tkfont.nametofont("TkDefaultFont").copy()
        bold.configure(weight="bold", size=int(bold.cget("size")) + 2)
        self._bold = bold

        frame = ttk.Frame(root, padding=16)
        frame.grid()
        ttk.Label(frame, text="Sidekick is running", font=bold).grid(row=0, column=0, sticky="w")
        self.howto_label = ttk.Label(frame, text="", justify="left")
        self.howto_label.grid(row=1, column=0, sticky="w", pady=(8, 8))
        self.hotkey_label = ttk.Label(frame, text="", wraplength=380, justify="left")
        self.hotkey_label.grid(row=2, column=0, sticky="w")
        self.key_label = ttk.Label(frame, text="", wraplength=380, justify="left")
        self.key_label.grid(row=3, column=0, sticky="w", pady=(4, 0))
        self.spend_label = ttk.Label(frame, text="")
        self.spend_label.grid(row=4, column=0, sticky="w", pady=(4, 0))

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, sticky="w", pady=(12, 0))
        ttk.Button(buttons, text="Ask now", command=lambda: self.open_popup(None)).grid(row=0, column=0)
        ttk.Button(buttons, text="Settings", command=self.open_settings).grid(row=0, column=1, padx=6)
        ttk.Button(buttons, text="Quit", command=self.quit).grid(row=0, column=2)

    def ask_label(self) -> str:
        """The text on the Ask window's main button."""
        return "Ask" if self.settings.send_to == "api" else "Open in Claude"

    def refresh_main(self) -> None:
        """Bring the main window's text up to date."""
        s = self.settings
        key = self.active_hotkey.pretty() if self.active_hotkey else ""
        press = f"Press {key}" if key else "Click the Ask now button below"
        inside = s.send_to == "api"
        one_key = s.instant and s.hotkey_action != "open"
        snip = " (or snip the screen with Win+Shift+S)" if services.reads_pictures(s) else ""
        if one_key:
            action = HOTKEY_ACTIONS[s.hotkey_action][0].split(" (")[0]
            result = ("The answer appears in a small window. Copy it, or click Paste back."
                      if inside else "Claude opens with the question filled in. Press Enter there.")
            steps = (
                f"1. Select text in any app{snip}.\n"
                f"2. {press}. Sidekick copies it and asks \"{action}\" right away.\n"
                f"3. {result}\n\n"
                f"With nothing selected, {(key or 'the hotkey')} opens the window so you can type a question."
            )
        else:
            steps = (
                f"1. Copy text (Ctrl+C){snip}.\n"
                f"2. {press}.{' This works in any app.' if key else ''}\n"
                f"3. Type your question and click {self.ask_label()}.\n"
                + ("" if inside else "4. Claude opens with your question. Press Enter there.\n")
                + "\nNothing is sent until you say so."
            )
        self.howto_label.configure(text=steps + "\nYou can minimize this window. Sidekick keeps running.")
        if self.active_hotkey:
            text = f"Hotkey: {self.active_hotkey.pretty()}"
            if self.hotkey_note:
                text += f"\n{self.hotkey_note}"
        else:
            text = self.hotkey_note or "No hotkey is active."
        self.hotkey_label.configure(text=text)

        if self.settings.send_to != "api":
            where = "the Claude app" if self.settings.send_to == "claude_app" else "the Claude website in Chrome"
            self.key_label.configure(text=f"Questions open in {where}.\nThis uses your Claude plan: no API key, no extra bill.")
            self.spend_label.configure(text="")
            return

        key_text = f"Answers appear here in Sidekick, from {services.describe(self.settings)}."
        provider = self.settings.provider
        if provider == "claude_code" and not find_claude(self.settings.claude_code_command):
            key_text += ("\nClaude Code was not found on this PC yet: install it for the terminal "
                         "and sign in (see Settings > AI service). Sidekick finds it by itself after that.")
        if provider in ("claude", "gemini"):
            if services.load_key(provider):
                key_text += " API key: saved"
            elif provider == "claude" and keystore.env_has_credentials():
                key_text += " API key: taken from ANTHROPIC_API_KEY"
            else:
                key_text += " API key: not set yet. Click Settings to add it."
        self.key_label.configure(text=key_text)

        if not services.counts_spending(self.settings):
            self.spend_label.configure(text="")  # no prices for this service: nothing to count
            return
        spent, limit = self.spend.today_total(), self.settings.daily_limit_usd
        spent_text = f"about {format_money(spent)}" if spent > 0 else "$0.00"
        limit_text = f" of your ${limit:.2f} daily limit" if limit > 0 else ""
        self.spend_label.configure(text=f"Spent today: {spent_text}{limit_text}")

    # ------------------------------------------------------------ hotkey

    def _apply_hotkey(self) -> None:
        """Ask the system for the hotkey; if another app has it, try the
        backup one and say so."""
        self.active_hotkey = None
        self.hotkey_note = ""
        self.platform.stop_hotkey()
        if self.platform.name == "generic":
            self.hotkey_note = "Global hotkeys need Windows. On this computer, use the Ask now button."
            return
        try:
            wanted = parse_hotkey(self.settings.hotkey)
        except ValueError:
            wanted = parse_hotkey(DEFAULT_HOTKEY)

        ok, problem = self.platform.start_hotkey(wanted, self._on_hotkey)
        if ok:
            self.active_hotkey = wanted
            return
        log.warning("Hotkey %s unavailable: %s", wanted, problem)
        backup = parse_hotkey(FALLBACK_HOTKEY)
        if backup != wanted:
            ok, _ = self.platform.start_hotkey(backup, self._on_hotkey)
            if ok:
                self.active_hotkey = backup
                self.hotkey_note = (
                    f"{wanted.pretty()} is already used by another app, so Sidekick is using "
                    f"{backup.pretty()} instead. You can pick another hotkey in Settings."
                )
                return
        self.hotkey_note = (
            f"The hotkey {wanted.pretty()} is already used by another app. "
            "Pick a different one in Settings, or use the Ask now button."
        )

    def _tick(self) -> None:
        try:
            self.process_events()
        finally:
            self._tick_job = self.root.after(150, self._tick)

    def _on_hotkey(self, window: WindowInfo | None) -> None:
        """Runs on the hotkey thread the moment the hotkey is pressed, while
        your app is still in front: in one-key mode, copy its selection.
        Nothing here touches Sidekick's windows."""
        s = self.settings
        copied = False
        if (s.instant and window is not None and window.pid != os.getpid()
                and not is_private_window(window, s.private_words)):
            try:
                copied = self.platform.copy_selection(window)
            except Exception:
                log.exception("Copying the selection failed")
        self.hotkey_events.put((window, copied))

    def process_events(self) -> None:
        """Runs a few times a second: notice clipboard changes and hotkey presses."""
        self.watch.poll()
        pressed, window, copied = False, None, False
        try:
            while True:
                window, copied = self.hotkey_events.get_nowait()
                pressed = True
        except queue.Empty:
            pass
        if pressed:
            self.open_popup(window, copied)

    # ------------------------------------------------------------- popup

    def read_clipboard_text(self) -> str:
        # Windows understands the plain request; some other systems need the
        # UTF8_STRING one. Try both.
        for options in ({"type": "UTF8_STRING"}, {}):
            try:
                return self.root.clipboard_get(**options)
            except tk.TclError:
                continue
        return ""

    def open_popup(self, window: WindowInfo | None, copied: bool = False) -> None:
        """Show the Ask window for a hotkey press (or the Ask now button).
        `copied` means Sidekick just copied your selection (one-key mode)."""
        s = self.settings
        if window is not None and window.pid == os.getpid():
            # The hotkey was pressed while Sidekick itself was in front.
            if self.popup.visible:
                self.popup.focus()
                return
            window = None
        capture = None
        if copied:
            text = self.read_clipboard_text()
            if text.strip():
                limit = s.max_text_chars
                note = "Sidekick copied your selection."
                if len(text) > limit:
                    note = f"Sidekick copied your selection and kept the first {limit:,} characters."
                capture = Capture(window=window, text=text[:limit], note=note)
            # (no text: maybe a file selected in File Explorer, which the
            # usual clipboard rules below pick up)
        if capture is None:
            capture = capture_context(
                window, self.watch, self.platform, self.read_clipboard_text,
                self.platform.grab_clipboard_media, s,
            )
        if copied:
            self.watch.note_own_copy(capture.text)  # don't reuse it on the next press
        self.popup.open(capture)

        snip = capture.attachment is not None and capture.attachment.kind == "image" and not capture.attachment.path
        has_content = bool(capture.text.strip() or capture.attachment)
        if s.instant and s.hotkey_action != "open" and has_content and (copied or snip):
            if snip and not services.reads_pictures(s):
                self.popup.set_note("This picture was not sent. " + NO_PICTURES)
            else:
                label, prompt = HOTKEY_ACTIONS[s.hotkey_action]
                self.popup.auto_ask(prompt, label.split(" (")[0])

    # ------------------------------------------------------------ Claude

    def has_key(self) -> bool:
        return services.has_key(self.settings)

    def client(self):
        if self._client is None:
            self._client = self._client_factory(self.settings)
        return self._client

    def paste_back(self, text: str, window: WindowInfo | None) -> None:
        """Put the answer into the app you were in (as if you pressed Ctrl+V)."""
        self.copy_to_clipboard(text)
        self.popup.hide()
        self.root.update_idletasks()

        def paste() -> None:
            if not self.platform.paste_into(window):
                self.show_toast("The answer is copied. Click where you want it, then press Ctrl+V.")

        self.root.after(60, paste)

    def on_key_changed(self) -> None:
        self._client = None
        self.refresh_main()

    def on_settings_changed(self, hotkey_changed: bool) -> None:
        self._client = None
        if hotkey_changed:
            self._apply_hotkey()
        self.popup.refresh_mode()
        self.refresh_main()

    # ------------------------------------------- Claude app / website

    def copy_to_clipboard(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()
        self.watch.note_own_copy(text)  # not to be mistaken for something you copied

    def hand_off(self, prompt: str, attachment=None, picture_on_clipboard: bool = False) -> bool:
        """Open a new Claude chat with `prompt` filled in, using the Claude
        app or the website as chosen in Settings. Shows a short note saying
        what to do next. Returns False if nothing could be opened."""
        p = self.platform
        path = attachment.path if attachment is not None else None
        notes: list[str] = []

        def plan_for(target: str):
            return plan_handoff(target, prompt, attachment, path or None, picture_on_clipboard)

        target = self.settings.send_to
        if target == "claude_app" and not p.claude_app_installed():
            notes.append("The Claude app is not installed, so Claude opens on its website instead.")
            target = "chrome"
        plan = plan_for(target)
        opened_in = ""
        if plan.target == "claude_app":
            if plan.clipboard_text:
                self.copy_to_clipboard(plan.clipboard_text)
            if p.open_link(plan.url):
                opened_in = "claude_app"
            else:
                notes.append("The Claude app did not open, so Claude opens on its website instead.")
                plan = plan_for("chrome")
        if not opened_in:
            if plan.clipboard_text:
                self.copy_to_clipboard(plan.clipboard_text)
            if p.open_in_chrome(plan.url):
                opened_in = "chrome"
            elif p.open_link(plan.url):
                opened_in = "browser"
                if self.settings.send_to == "chrome":
                    notes.append("Chrome was not found, so your usual web browser was used.")
        if not opened_in:
            self.copy_to_clipboard(prompt)
            self.dialogs.error(
                self.root, "Could not open Claude",
                "Sidekick could not open the Claude app or a web browser.\n\n"
                "Your question is copied: open claude.ai yourself, press Ctrl+V, then Enter.",
            )
            return False
        if plan.reveal_file:
            p.reveal_file(plan.reveal_file)

        lines = notes + [f"Claude is opening in {TARGET_NAMES[opened_in]}. Then:"]
        lines += [f"{i}. {step}" for i, step in enumerate(plan.steps, 1)]
        self.show_toast("\n".join(lines))
        return True

    def show_toast(self, text: str, seconds: float = 12.0) -> None:
        """A small note at the top of the screen that disappears by itself
        (or when clicked). It stays above other windows, so it can be read
        while Claude opens."""
        self.close_toast()
        win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)  # no title bar
        win.attributes("-topmost", True)
        frame = tk.Frame(win, background="#1f2937", padx=16, pady=12)
        frame.pack()
        label = tk.Label(frame, text=text, justify="left", wraplength=460,
                         background="#1f2937", foreground="#ffffff")
        label.pack()
        hint = tk.Label(frame, text="(click to close)", background="#1f2937", foreground="#9ca3af")
        hint.pack(anchor="e", pady=(6, 0))
        for widget in (win, frame, label, hint):
            widget.bind("<Button-1>", lambda _e: self.close_toast())
        win.update_idletasks()
        x = max(0, (win.winfo_screenwidth() - win.winfo_reqwidth()) // 2)
        win.geometry(f"+{x}+48")
        win.deiconify()
        self.toast = win
        self.toast_text = text
        self._toast_job = self.root.after(int(seconds * 1000), self.close_toast)

    def close_toast(self) -> None:
        if self._toast_job is not None:
            try:
                self.root.after_cancel(self._toast_job)
            except tk.TclError:
                pass
            self._toast_job = None
        if self.toast is not None:
            try:
                self.toast.destroy()
            except tk.TclError:
                pass
            self.toast = None

    def open_settings(self, reason: str = "") -> None:
        if self.settings_dialog is not None and self.settings_dialog.alive:
            self.settings_dialog.win.lift()
            return
        self.settings_dialog = SettingsDialog(self, reason)

    # -------------------------------------------------------------- exit

    def on_close(self) -> None:
        if self.dialogs.confirm(
            self.root, "Quit Sidekick?",
            "Quit Sidekick?\n\nYes: quit (the hotkey stops working).\nNo: keep it running, minimized.",
        ):
            self.quit()
        else:
            self.root.iconify()

    def quit(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.platform.stop_hotkey()
        try:
            self.root.after_cancel(self._tick_job)
            self.close_toast()
            self.popup.hide()
        except tk.TclError:
            pass
        self.root.destroy()

    def _on_window_error(self, exc_type, exc, tb) -> None:
        log.error("Unexpected error in the window code", exc_info=(exc_type, exc, tb))


def setup_logging() -> Path:
    """Write problems to a small log file (there is no console window).
    Questions, answers and copied text are never written to the log."""
    folder = config_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "sidekick.log"
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=200_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    return path


def main() -> int:
    log_path = None
    try:
        log_path = setup_logging()
        platform = get_platform()
        platform.prepare_process()
        root = tk.Tk()
        if not platform.acquire_single_instance():
            root.withdraw()
            Dialogs().info(root, "Sidekick", "Sidekick is already running. Look for it on the taskbar.")
            return 0
        SidekickApp(root, platform, load_settings(), DailySpend(config_dir() / "usage.json"))
        root.mainloop()
        return 0
    except Exception as e:
        log.exception("Sidekick could not start")
        try:
            from tkinter import messagebox

            messagebox.showerror(
                "Sidekick could not start",
                f"{type(e).__name__}: {e}\n\nDetails were saved to:\n{log_path}",
            )
        except Exception:
            print(f"Sidekick could not start: {e}", file=sys.stderr)
        return 1
