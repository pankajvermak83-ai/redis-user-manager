"""The Settings window (two tabs: General, and AI service)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import keystore
from .claude_code_client import find_claude
from .config import (
    CLAUDE_CODE_MODELS, CLAUDE_MODEL_IDS, DEFAULT_GEMINI_MODEL, DEFAULT_MODEL, DEFAULT_OLLAMA_MODEL,
    EFFORTS, GEMINI_MODELS, HOTKEY_ACTIONS, OLLAMA_MODELS, OLLAMA_URL, PROVIDERS, SEND_TO_CHOICES,
    save_settings,
)
from .costs import PRICES
from .hotkeys import parse_hotkey

# Ctrl+Alt+Space is left out on purpose: the Claude app may use it.
HOTKEY_CHOICES = [
    "ctrl+shift+space",
    "ctrl+alt+shift+space",
    "ctrl+shift+f9",
    "win+shift+a",
]
SEND_TO_LABELS = {
    "claude_app": "The Claude app on this PC (your Claude plan, no extra cost)",
    "chrome": "The Claude website in Chrome (your Claude plan, no extra cost)",
    "api": "Answer inside Sidekick (choose the AI on the \"AI service\" tab)",
}
EFFORT_LABELS = {
    "low": "Low - quickest and cheapest",
    "medium": "Medium - balanced (recommended)",
    "high": "High - thinks longer, costs more",
}
PROVIDER_LABELS = {
    "claude_code": "Claude Code on this PC (your Claude plan, no API key)",
    "claude": "Claude API (best answers, pay per use)",
    "gemini": "Google Gemini API (has a small free tier)",
    "ollama": "Ollama on this PC (free, private, works offline)",
    "custom": "Other service (any OpenAI-compatible API)",
}
# provider: (key store slot, label, where to get a key, check, what a key looks like)
KEY_INFO = {
    "claude": (keystore.ACCOUNT, "Claude API key:",
               "Create a key at platform.claude.com/settings/keys. API use is billed separately from a Claude plan.",
               keystore.looks_like_anthropic_key, 'Anthropic API keys normally start with "sk-ant-".'),
    "gemini": (keystore.GEMINI_ACCOUNT, "Gemini API key:",
               "Get a key in Google AI Studio (aistudio.google.com). On the free tier Google may use what you "
               "send to improve its products, and people may read it: don't send private or confidential text.",
               keystore.looks_like_gemini_key, 'Gemini API keys normally start with "AIza".'),
    "custom": (keystore.CUSTOM_ACCOUNT, "API key:",
               "The key from the service's website. Leave it empty if the service needs none.", None, ""),
}
ENV_KEYS = {"claude": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY"}


class SettingsDialog:
    def __init__(self, app, reason: str = ""):
        self.app = app
        s = app.settings
        self._prices = {p: list(v) for p, v in s.prices.items()}
        self._provider = s.provider if s.provider in PROVIDERS else PROVIDERS[0]

        self.win = tk.Toplevel(app.root)
        self.win.title("Sidekick Settings")
        self.win.resizable(False, False)
        # Not "always on top": on Windows, a dropdown list then opens behind
        # this window, so nothing can be picked from it. The Ask window is
        # moved out of the way instead, so it can't cover this one.
        popup = getattr(app, "popup", None)
        if popup is not None:
            try:
                popup.win.attributes("-topmost", False)
            except tk.TclError:
                pass
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", lambda _e: self.close())

        outer = ttk.Frame(self.win, padding=12)
        outer.grid()
        if reason:
            ttk.Label(outer, text=reason, wraplength=500, justify="left").grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.tabs = ttk.Notebook(outer)
        self.tabs.grid(row=1, column=0, sticky="nsew")
        general = ttk.Frame(self.tabs, padding=10)
        ai = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(general, text="General")
        self.tabs.add(ai, text="AI service")
        self._build_general(general, s)
        self._build_ai(ai, s)

        buttons = ttk.Frame(outer)
        buttons.grid(row=2, column=0, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Save", command=self.on_save).grid(row=0, column=0)
        ttk.Button(buttons, text="Cancel", command=self.close).grid(row=0, column=1, padx=(6, 0))

        self._show_provider(self._provider, first=True)
        self._update_mode_note()
        if reason:
            self.tabs.select(ai)
        self.win.lift()
        self.win.focus_force()
        (self.key_entry if reason and self._provider in KEY_INFO else self.send_to_box).focus_set()
        # A click anywhere on a list box opens its list (not only on the arrow).
        for box in _comboboxes(self.win):
            box.bind("<Button-1>", _open_list, add="+")

    # ------------------------------------------------------------ layout

    def _build_general(self, frame, s) -> None:
        frame.columnconfigure(1, weight=1)
        row = 0

        def add(label: str, widget, pad: int = 8) -> None:
            nonlocal row
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=(pad, 0))
            widget.grid(row=row, column=1, sticky="we", padx=(10, 0), pady=(pad, 0))
            row += 1

        def note(text: str) -> None:
            nonlocal row
            ttk.Label(frame, text=text, wraplength=500, justify="left").grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
            row += 1

        self._send_to_ids = list(SEND_TO_CHOICES)
        self.send_to_box = ttk.Combobox(frame, state="readonly", width=56,
                                        values=[SEND_TO_LABELS[t] for t in self._send_to_ids])
        self.send_to_box.current(self._send_to_ids.index(s.send_to) if s.send_to in SEND_TO_CHOICES else 0)
        self.send_to_box.bind("<<ComboboxSelected>>", lambda _e: self._update_mode_note())
        add("Send questions to:", self.send_to_box, pad=0)
        note("The Claude app and website open with the question filled in, and you press Enter there. "
             "\"Answer inside Sidekick\" needs no Enter: the answer appears right away, and with Claude Code "
             "it also uses your Claude plan, pictures and PDFs included.")

        self.instant_var = tk.BooleanVar(value=s.instant)
        ttk.Checkbutton(frame, variable=self.instant_var,
                        text="One key: pressing the hotkey copies the selected text and asks right away").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(10, 0))
        row += 1
        self._action_ids = list(HOTKEY_ACTIONS)
        self.action_box = ttk.Combobox(frame, state="readonly", width=56,
                                       values=[HOTKEY_ACTIONS[a][0] for a in self._action_ids])
        self.action_box.current(self._action_ids.index(s.hotkey_action) if s.hotkey_action in HOTKEY_ACTIONS else 0)
        add("The hotkey asks:", self.action_box)
        note("To do this, Sidekick presses Ctrl+Insert (or Ctrl+C) in your app for you. "
             "It never does this in private windows, and never presses Ctrl+C in terminals.")

        self.hotkey_var = tk.StringVar(value=s.hotkey)
        choices = HOTKEY_CHOICES if s.hotkey in HOTKEY_CHOICES else [s.hotkey, *HOTKEY_CHOICES]
        self.hotkey_box = ttk.Combobox(frame, textvariable=self.hotkey_var, width=56, values=choices)
        add("Hotkey:", self.hotkey_box, pad=10)

        self.title_var = tk.BooleanVar(value=s.send_window_title)
        ttk.Checkbutton(frame, variable=self.title_var,
                        text="Tell the AI which app and window I was in (helps it give exact steps)").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(10, 0))
        row += 1
        note("Private words: if a window's name contains one of these, Sidekick reads nothing from it. One per line.")
        self.private_text = tk.Text(frame, height=4, width=60, wrap="word")
        self.private_text.grid(row=row, column=0, columnspan=2, sticky="we", pady=(2, 0))
        self.private_text.insert("1.0", "\n".join(s.private_words))

    def _build_ai(self, frame, s) -> None:
        frame.columnconfigure(1, weight=1)
        self.mode_note = ttk.Label(frame, wraplength=500, justify="left", text="")
        self.mode_note.grid(row=0, column=0, columnspan=2, sticky="w")
        self._provider_ids = list(PROVIDERS)
        self.provider_box = ttk.Combobox(frame, state="readonly", width=52,
                                         values=[PROVIDER_LABELS[p] for p in self._provider_ids])
        self.provider_box.current(self._provider_ids.index(self._provider))
        self.provider_box.bind("<<ComboboxSelected>>", lambda _e: self._show_provider(self._selected_provider()))
        ttk.Label(frame, text="AI service:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.provider_box.grid(row=1, column=1, sticky="we", padx=(10, 0), pady=(10, 0))

        holder = ttk.Frame(frame)
        holder.grid(row=2, column=0, columnspan=2, sticky="we", pady=(8, 0))
        holder.columnconfigure(0, weight=1)
        self.service_frames = {p: ttk.Frame(holder) for p in PROVIDERS}
        for f in self.service_frames.values():
            f.columnconfigure(1, weight=1)

        def field(parent, row: int, label: str, widget) -> None:
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=(6, 0))
            widget.grid(row=row, column=1, sticky="we", padx=(10, 0), pady=(6, 0))

        def tip(parent, row: int, text: str) -> ttk.Label:
            label = ttk.Label(parent, text=text, wraplength=500, justify="left")
            label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
            return label

        # Claude Code
        f = self.service_frames["claude_code"]
        self.code_model_var = tk.StringVar(value=s.claude_code_model or "default")
        self.code_model_box = ttk.Combobox(f, textvariable=self.code_model_var, width=40,
                                           values=["default" if m == "" else m for m in CLAUDE_CODE_MODELS])
        field(f, 0, "Model:", self.code_model_box)
        found = find_claude(s.claude_code_command)
        self.code_status = tip(f, 1, (
            f"Claude Code was found ({found}). It must be signed in with your Claude account "
            "(run claude once in a terminal)." if found else
            "Claude Code was not found. (The VS Code extension's copy can't be used.) Install it for the "
            "terminal from code.claude.com, run claude once to sign in, then restart Sidekick."))
        tip(f, 2, "Needs a paid Claude plan (Pro or higher). Answers count toward your plan's usage limits "
                  "(shared with Claude chat and Claude Code); there is no extra bill unless you turned on "
                  "usage credits in Claude's settings. Sidekick removes any API key when it runs Claude Code, "
                  "so your plan is used. Tools are off and your own CLAUDE.md, hooks and plugins are not "
                  "loaded (safe mode), so it only answers. Pictures and PDFs work too.")

        # Claude API
        f = self.service_frames["claude"]
        self.model_var = tk.StringVar(value=s.model)
        self.model_box = ttk.Combobox(f, textvariable=self.model_var, width=40, values=list(CLAUDE_MODEL_IDS))
        field(f, 0, "Claude model:", self.model_box)
        self._efforts = list(EFFORTS)
        self.effort_box = ttk.Combobox(f, state="readonly", width=40, values=[EFFORT_LABELS[e] for e in self._efforts])
        self.effort_box.current(self._efforts.index(s.effort) if s.effort in EFFORTS else 1)
        field(f, 1, "Thinking effort:", self.effort_box)
        tip(f, 2, "Opus is the smartest; Haiku is the fastest and costs about 1/40 as much "
                  "(often well under 0.1 cent a question). You can also type a newer model's name.")

        # Gemini
        f = self.service_frames["gemini"]
        self.gemini_model_var = tk.StringVar(value=s.gemini_model)
        field(f, 0, "Gemini model:", ttk.Combobox(f, textvariable=self.gemini_model_var, width=40,
                                                 values=list(GEMINI_MODELS)))
        tip(f, 1, "Free tier (late 2026): about 500 questions a day with gemini-3.5-flash-lite, about 20 a day "
                  "with gemini-3.8-flash. Limits change: see aistudio.google.com.")

        # Ollama
        f = self.service_frames["ollama"]
        self.ollama_model_var = tk.StringVar(value=s.ollama_model)
        field(f, 0, "Model:", ttk.Combobox(f, textvariable=self.ollama_model_var, width=40, values=list(OLLAMA_MODELS)))
        self.ollama_url_var = tk.StringVar(value=s.ollama_url)
        field(f, 1, "Address:", ttk.Entry(f, textvariable=self.ollama_url_var, width=42))
        tip(f, 2, "Install Ollama from ollama.com, then download a model once, for example in a terminal:\n"
                  "ollama pull gemma4:e4b      (use gemma4:e2b on a PC with 8 GB of memory)\n"
                  "Everything stays on this PC.")

        # Other service
        f = self.service_frames["custom"]
        self.custom_name_var = tk.StringVar(value=s.custom_name)
        field(f, 0, "Name (any):", ttk.Entry(f, textvariable=self.custom_name_var, width=42))
        self.custom_url_var = tk.StringVar(value=s.custom_url)
        field(f, 1, "Address:", ttk.Entry(f, textvariable=self.custom_url_var, width=42))
        self.custom_model_var = tk.StringVar(value=s.custom_model)
        field(f, 2, "Model:", ttk.Entry(f, textvariable=self.custom_model_var, width=42))
        tip(f, 3, "Any service with an OpenAI-compatible chat API: copy the \"base URL\" and a model "
                  "name from its documentation, for example https://api.openai.com/v1 or "
                  "http://localhost:1234/v1 (LM Studio).")

        # API key (Claude API, Gemini, other)
        self.key_frame = ttk.Frame(frame)
        self.key_frame.grid(row=3, column=0, columnspan=2, sticky="we", pady=(10, 0))
        self.key_frame.columnconfigure(1, weight=1)
        self.key_label = ttk.Label(self.key_frame, text="API key:")
        self.key_label.grid(row=0, column=0, sticky="w")
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(self.key_frame, textvariable=self.key_var, show="*", width=34)
        self.key_entry.grid(row=0, column=1, sticky="we", padx=(10, 0))
        ttk.Button(self.key_frame, text="Save key", command=self.on_save_key).grid(row=0, column=2, padx=(6, 0))
        ttk.Button(self.key_frame, text="Remove", command=self.on_remove_key).grid(row=0, column=3, padx=(6, 0))
        self.key_status = ttk.Label(self.key_frame, text="", wraplength=500, justify="left")
        self.key_status.grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))
        self.key_help = ttk.Label(self.key_frame, text="", wraplength=500, justify="left")
        self.key_help.grid(row=2, column=0, columnspan=4, sticky="w", pady=(2, 0))

        # Prices and limit
        money = ttk.Frame(frame)
        money.grid(row=4, column=0, columnspan=2, sticky="we", pady=(10, 0))
        ttk.Label(money, text="Your prices, $ per million tokens:  input").grid(row=0, column=0, sticky="w")
        self.price_in_var = tk.StringVar()
        ttk.Entry(money, textvariable=self.price_in_var, width=8).grid(row=0, column=1, padx=(6, 0))
        ttk.Label(money, text="output").grid(row=0, column=2, padx=(10, 0))
        self.price_out_var = tk.StringVar()
        ttk.Entry(money, textvariable=self.price_out_var, width=8).grid(row=0, column=3, padx=(6, 0))
        self.price_help = ttk.Label(money, text="", wraplength=500, justify="left")
        self.price_help.grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 0))
        ttk.Label(money, text="Daily limit in $ (0 = none):").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.limit_var = tk.StringVar(value=f"{s.daily_limit_usd:.2f}")
        ttk.Entry(money, textvariable=self.limit_var, width=8).grid(row=2, column=1, padx=(6, 0), pady=(8, 0))

    # ------------------------------------------------------------ helpers

    @property
    def alive(self) -> bool:
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def close(self) -> None:
        if self.alive:
            self.win.destroy()

    def _update_mode_note(self) -> None:
        """Say whether the AI service and model below are in use right now."""
        if self._send_to_ids[self.send_to_box.current()] == "api":
            text = ("Pick the AI service first, then its model below. You can switch at any time, "
                    "for example if prices change.")
        else:
            text = ("Not in use now: questions open in the Claude app or website, which uses its own "
                    "model. To use the AI service and model below, set \"Send questions to\" on the "
                    "General tab to \"Answer inside Sidekick\".")
        self.mode_note.configure(text=text)

    def _selected_provider(self) -> str:
        return self._provider_ids[self.provider_box.current()]

    def _show_provider(self, provider: str, first: bool = False) -> None:
        """Show the fields for the chosen AI service."""
        if not first:
            self._remember_prices(self._provider)
        self._provider = provider
        for name, frame in self.service_frames.items():
            if name == provider:
                frame.grid(row=0, column=0, sticky="we")
            else:
                frame.grid_remove()
        if provider in KEY_INFO:
            account, label, help_text, _check, _shape = KEY_INFO[provider]
            self.key_label.configure(text=label)
            self.key_help.configure(text=help_text)
            self.key_frame.grid()
        else:
            self.key_frame.grid_remove()
        self.key_var.set("")
        self._refresh_key_status()
        pair = self._prices.get(provider)
        self.price_in_var.set(_number(pair[0]) if pair else "")
        self.price_out_var.set(_number(pair[1]) if pair else "")
        if provider == "claude":
            builtin = PRICES.get(self.model_var.get().strip(), PRICES[DEFAULT_MODEL])
            help_text = (f"Leave empty to use Sidekick's built-in Claude prices (now ${_number(builtin[0])} in, "
                         f"${_number(builtin[1])} out for this model). Fill in if prices change.")
        elif provider == "claude_code":
            help_text = "Claude Code uses your Claude plan, so Sidekick does not count costs for it."
        else:
            help_text = ("Leave empty if it is free (Ollama, Gemini's free tier). Fill in the service's prices "
                         "to get cost estimates and to use the daily limit.")
        self.price_help.configure(text=help_text)

    def _remember_prices(self, provider: str) -> bool:
        """Keep what was typed in the price boxes for `provider`.
        False (and an error message) if it isn't two numbers."""
        a, b = self.price_in_var.get().strip(), self.price_out_var.get().strip()
        if not a and not b:
            self._prices.pop(provider, None)
            return True
        try:
            pair = [float(a.replace("$", "")), float(b.replace("$", ""))]
            if not all(0 <= v <= 1000 for v in pair):
                raise ValueError
        except ValueError:
            self.app.dialogs.error(self.win, "Prices", "Type both prices as numbers, for example 0.10 and 0.50, "
                                                       "or leave both empty.")
            return False
        self._prices[provider] = pair
        return True

    # ------------------------------------------------------------ API keys

    def _refresh_key_status(self) -> None:
        provider = self._provider
        if provider not in KEY_INFO:
            return
        account = KEY_INFO[provider][0]
        env_name = ENV_KEYS.get(provider)
        if keystore.load_api_key(account):
            text = "A key is saved on this computer."
        elif provider == "claude" and keystore.env_has_credentials():
            text = "Using the ANTHROPIC_API_KEY that is set on this computer."
        elif provider == "gemini" and keystore.env_gemini_key():
            text = f"Using the {env_name} that is set on this computer."
        elif provider == "custom":
            text = "No key saved (fine if the service needs none)."
        else:
            text = "No key saved. You need one for this AI service."
        self.key_status.configure(text=text)

    def on_save_key(self) -> None:
        provider = self._provider
        if provider not in KEY_INFO:
            return
        account, _label, _help, check, shape = KEY_INFO[provider]
        key = self.key_var.get().strip()
        dialogs = self.app.dialogs
        if not key:
            dialogs.error(self.win, "No key", "Paste your API key into the box first.")
            return
        if check is not None and not check(key) and not dialogs.confirm(
            self.win, "Check the key", f"{shape} This one does not.\n\nSave it anyway?",
        ):
            return
        try:
            keystore.save_api_key(key, account)
        except keystore.KeyStoreError as e:
            dialogs.error(self.win, "Could not save the key", str(e))
            return
        self.key_var.set("")
        self.app.on_key_changed()
        self._refresh_key_status()

    def on_remove_key(self) -> None:
        if self._provider in KEY_INFO:
            keystore.delete_api_key(KEY_INFO[self._provider][0])
        self.key_var.set("")
        self.app.on_key_changed()
        self._refresh_key_status()

    # --------------------------------------------------------------- save

    def on_save(self) -> None:
        app, dialogs, s = self.app, self.app.dialogs, self.app.settings
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
        if not self._remember_prices(self._provider):
            return
        provider = self._selected_provider()
        claude_model = self.model_var.get().strip() or DEFAULT_MODEL
        if not claude_model.startswith("claude-"):
            dialogs.error(self.win, "Claude model", "Claude model names start with \"claude-\", for example claude-haiku-5-5.")
            return
        ollama_url = self.ollama_url_var.get().strip().rstrip("/") or OLLAMA_URL
        custom_url = self.custom_url_var.get().strip().rstrip("/")
        if not ollama_url.startswith(("http://", "https://")) or (custom_url and not custom_url.startswith(("http://", "https://"))):
            dialogs.error(self.win, "Address", "An address must start with http:// or https://")
            return
        if provider == "custom" and not (custom_url and self.custom_model_var.get().strip()):
            dialogs.error(self.win, "Other service", "Fill in the service's address and a model name.")
            return

        old_hotkey = s.hotkey
        s.send_to = self._send_to_ids[self.send_to_box.current()]
        s.instant = bool(self.instant_var.get())
        s.hotkey_action = self._action_ids[self.action_box.current()]
        s.provider = provider
        s.model = claude_model
        s.effort = self._efforts[self.effort_box.current()]
        code_model = self.code_model_var.get().strip()
        s.claude_code_model = "" if code_model in ("", "default") else code_model
        s.gemini_model = self.gemini_model_var.get().strip() or DEFAULT_GEMINI_MODEL
        s.ollama_model = self.ollama_model_var.get().strip() or DEFAULT_OLLAMA_MODEL
        s.ollama_url = ollama_url
        s.custom_name = self.custom_name_var.get().strip()
        s.custom_url = custom_url
        s.custom_model = self.custom_model_var.get().strip()
        s.prices = {p: list(v) for p, v in self._prices.items()}
        s.hotkey = str(hotkey)
        s.daily_limit_usd = limit
        s.send_window_title = bool(self.title_var.get())
        s.private_words = [w.strip().lower() for w in self.private_text.get("1.0", "end-1c").splitlines() if w.strip()]
        try:
            save_settings(s, app.settings_path)
        except OSError as e:
            dialogs.error(self.win, "Could not save", f"The settings file could not be written ({e}).")
            return
        app.on_settings_changed(hotkey_changed=(s.hotkey != old_hotkey))
        self.close()


def _number(value: float) -> str:
    return f"{value:g}"


def _comboboxes(widget) -> list:
    found = []
    for child in widget.winfo_children():
        if isinstance(child, ttk.Combobox):
            found.append(child)
        found.extend(_comboboxes(child))
    return found


def _open_list(event) -> None:
    """Open a list box's list when its text part is clicked. Read-only boxes
    already do this by themselves; boxes you can also type in only open from
    their arrow, which is easy to miss."""
    box = event.widget
    if str(box.cget("state")) == "readonly":
        return
    box.after_idle(lambda: _post(box))


def _post(box) -> None:
    try:
        box.tk.call("ttk::combobox::Post", box)
    except tk.TclError:
        pass  # this Tk has no such command: the arrow still works
