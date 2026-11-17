"""The Settings window."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import keystore
from .config import EFFORTS, MODELS, save_settings
from .hotkeys import parse_hotkey

HOTKEY_CHOICES = [
    "ctrl+shift+space",
    "ctrl+alt+shift+space",
    "ctrl+alt+space",
    "ctrl+shift+f9",
    "win+shift+a",
]
EFFORT_LABELS = {
    "low": "Low - quickest and cheapest",
    "medium": "Medium - balanced (recommended)",
    "high": "High - thinks longer, costs more",
}


class SettingsDialog:
    def __init__(self, app, reason: str = ""):
        self.app = app
        settings = app.settings
        self.win = tk.Toplevel(app.root)
        self.win.title("Sidekick Settings")
        self.win.resizable(False, False)
        self.win.attributes("-topmost", True)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", lambda _e: self.close())

        frame = ttk.Frame(self.win, padding=14)
        frame.grid()
        row = 0
        if reason:
            ttk.Label(frame, text=reason, wraplength=440, justify="left").grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 10))
            row += 1

        # --- API key
        key_box = ttk.LabelFrame(frame, text="Anthropic API key", padding=8)
        key_box.grid(row=row, column=0, columnspan=2, sticky="we")
        row += 1
        self.key_status = ttk.Label(key_box, text="", wraplength=420, justify="left")
        self.key_status.grid(row=0, column=0, columnspan=3, sticky="w")
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(key_box, textvariable=self.key_var, show="*", width=44)
        self.key_entry.grid(row=1, column=0, sticky="we", pady=(6, 0))
        ttk.Button(key_box, text="Save key", command=self.on_save_key).grid(row=1, column=1, padx=(6, 0), pady=(6, 0))
        ttk.Button(key_box, text="Remove", command=self.on_remove_key).grid(row=1, column=2, padx=(6, 0), pady=(6, 0))
        ttk.Label(
            key_box, wraplength=420, justify="left",
            text="Get a key in the Anthropic Console (API keys), then paste it here. "
                 "It is stored in Windows Credential Manager, not in a file.",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # --- model and effort
        def add_row(label: str, widget: tk.Widget) -> None:
            nonlocal row
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=(10, 0))
            widget.grid(row=row, column=1, sticky="we", pady=(10, 0), padx=(10, 0))
            row += 1

        self._model_ids = list(MODELS)
        self.model_box = ttk.Combobox(frame, state="readonly", width=46, values=[MODELS[m].label for m in self._model_ids])
        self.model_box.current(self._model_ids.index(settings.model) if settings.model in MODELS else 0)
        add_row("Claude model:", self.model_box)

        self._efforts = list(EFFORTS)
        self.effort_box = ttk.Combobox(frame, state="readonly", width=46, values=[EFFORT_LABELS[e] for e in self._efforts])
        self.effort_box.current(self._efforts.index(settings.effort) if settings.effort in EFFORTS else 1)
        add_row("Thinking effort:", self.effort_box)

        self.hotkey_var = tk.StringVar(value=settings.hotkey)
        choices = HOTKEY_CHOICES if settings.hotkey in HOTKEY_CHOICES else [settings.hotkey, *HOTKEY_CHOICES]
        self.hotkey_box = ttk.Combobox(frame, textvariable=self.hotkey_var, width=46, values=choices)
        add_row("Hotkey:", self.hotkey_box)

        self.limit_var = tk.StringVar(value=f"{settings.daily_limit_usd:.2f}")
        add_row("Daily limit in $ (0 = none):", ttk.Entry(frame, textvariable=self.limit_var, width=12))

        self.title_var = tk.BooleanVar(value=settings.send_window_title)
        ttk.Checkbutton(
            frame, variable=self.title_var,
            text="Tell Claude which app and window I was in (helps it give exact steps)",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 0))
        row += 1

        ttk.Label(
            frame, wraplength=440, justify="left",
            text="Private words: if a window's name contains one of these, Sidekick reads nothing from it. One per line.",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 2))
        row += 1
        self.private_text = tk.Text(frame, height=5, width=52, wrap="word")
        self.private_text.grid(row=row, column=0, columnspan=2, sticky="we")
        self.private_text.insert("1.0", "\n".join(settings.private_words))
        row += 1

        buttons = ttk.Frame(frame)
        buttons.grid(row=row, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Save", command=self.on_save).grid(row=0, column=0)
        ttk.Button(buttons, text="Cancel", command=self.close).grid(row=0, column=1, padx=(6, 0))

        self._refresh_key_status()
        self.win.lift()
        self.key_entry.focus_set()

    @property
    def alive(self) -> bool:
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def close(self) -> None:
        if self.alive:
            self.win.destroy()

    # ------------------------------------------------------------ API key

    def _refresh_key_status(self) -> None:
        if keystore.load_api_key():
            text = "A key is saved on this computer."
        elif keystore.env_has_credentials():
            text = "Using the ANTHROPIC_API_KEY that is set on this computer."
        else:
            text = "No key yet. Sidekick cannot ask Claude until you add one."
        self.key_status.configure(text=text)

    def on_save_key(self) -> None:
        key = self.key_var.get().strip()
        dialogs = self.app.dialogs
        if not key:
            dialogs.error(self.win, "No key", "Paste your API key into the box first.")
            return
        if not keystore.looks_like_anthropic_key(key) and not dialogs.confirm(
            self.win, "Check the key",
            "Anthropic API keys normally start with \"sk-ant-\". This one does not.\n\nSave it anyway?",
        ):
            return
        try:
            keystore.save_api_key(key)
        except keystore.KeyStoreError as e:
            dialogs.error(self.win, "Could not save the key", str(e))
            return
        self.key_var.set("")
        self.app.on_key_changed()
        self._refresh_key_status()

    def on_remove_key(self) -> None:
        keystore.delete_api_key()
        self.key_var.set("")
        self.app.on_key_changed()
        self._refresh_key_status()

    # --------------------------------------------------------------- save

    def on_save(self) -> None:
        app, dialogs, settings = self.app, self.app.dialogs, self.app.settings
        try:
            hotkey = parse_hotkey(self.hotkey_var.get())
        except ValueError as e:
            dialogs.error(self.win, "Hotkey", str(e))
            return
        try:
            limit = float(self.limit_var.get().strip().replace("$", "") or "0")
            if limit < 0 or limit > 1000:
                raise ValueError
        except ValueError:
            dialogs.error(self.win, "Daily limit", "Type the daily limit as a number, for example 2 or 0.50.")
            return

        old_hotkey = settings.hotkey
        settings.model = self._model_ids[self.model_box.current()]
        settings.effort = self._efforts[self.effort_box.current()]
        settings.hotkey = str(hotkey)
        settings.daily_limit_usd = limit
        settings.send_window_title = bool(self.title_var.get())
        settings.private_words = [
            w.strip().lower() for w in self.private_text.get("1.0", "end-1c").splitlines() if w.strip()
        ]
        try:
            save_settings(settings, app.settings_path)
        except OSError as e:
            dialogs.error(self.win, "Could not save", f"The settings file could not be written ({e}).")
            return
        app.on_settings_changed(hotkey_changed=(settings.hotkey != old_hotkey))
        self.close()
