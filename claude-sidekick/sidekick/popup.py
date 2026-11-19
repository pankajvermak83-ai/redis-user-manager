"""The Ask window that appears when you press the hotkey."""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from .attachments import Attachment, AttachmentError, attachment_from_path, is_pdf, save_to_temp_file
from .capture import Capture, read_clipboard
from .claude_client import AskError, AskResult, Conversation
from . import services
from .config import PROVIDER_NAMES
from .costs import format_money, input_cost
from .handoff import build_chat_prompt
from .privacy import find_secrets
from .prompts import build_first_message, build_followup_message

log = logging.getLogger(__name__)

_UNEXPECTED = "Something unexpected went wrong. The details are in Sidekick's log file."


def _ask_worker(events: queue.Queue, rid: int, client, content: object,
                conversation: Conversation, stop: threading.Event) -> None:
    """Runs on a background thread: ask Claude and post what happens to
    `events`. Each message carries `rid` so the window can ignore replies to
    a question that was stopped or replaced."""
    try:
        result = client.ask(conversation, content, lambda piece: events.put((rid, "text", piece)), stop.is_set)
        events.put((rid, "done", result))
    except AskError as e:
        events.put((rid, "error", e))
    except Exception:
        log.exception("Unexpected error while asking Claude")
        events.put((rid, "error", AskError(_UNEXPECTED)))


def _read_worker(events: queue.Queue, rid: int, path: str, max_edge: int) -> None:
    """Runs on a background thread: open a file to attach (a big PDF's
    text can take a few seconds to read)."""
    try:
        events.put((rid, "attached", attachment_from_path(path, max_edge)))
    except AttachmentError as e:
        events.put((rid, "attach_error", str(e)))
    except Exception:
        log.exception("Reading a file to attach failed")
        events.put((rid, "attach_error", _UNEXPECTED))


def _count_worker(events: queue.Queue, rid: int, client, conversation: Conversation, content: object) -> None:
    """Runs on a background thread: find out how big a request would be."""
    try:
        tokens = client.count_input_tokens(conversation, content)
    except Exception:
        log.exception("Size check failed")
        tokens = None
    events.put((rid, "count", tokens))


class Dialogs:
    """Pop-up questions and messages. Kept in one place so the tests can
    answer them automatically."""

    def info(self, parent, title: str, message: str) -> None:
        messagebox.showinfo(title, message, parent=parent)

    def error(self, parent, title: str, message: str) -> None:
        messagebox.showerror(title, message, parent=parent)

    def confirm(self, parent, title: str, message: str) -> bool:
        return bool(messagebox.askyesno(title, message, parent=parent))

    def open_file(self, parent) -> str:
        return filedialog.askopenfilename(parent=parent, title="Attach a file") or ""


class Popup:
    """One window with three parts, top to bottom:
    what will be sent, your question, and Claude's answer."""

    def __init__(self, app):
        self.app = app
        self.conversation = Conversation()
        self.capture = Capture()
        self.attachment: Attachment | None = None
        self.last_answer = ""

        self._busy = False
        self._reading = False  # reading a file to attach (not asking)
        self._request_id = 0  # replies from older requests are ignored
        self._stop = threading.Event()
        self._events: queue.Queue = queue.Queue()
        self._got_text = False
        self._pending: tuple = ("", None)  # (question, content) waiting on a size check
        self._attachment_seq = None  # clipboard counter when a picture was picked up
        self._client = None  # the Claude client used by the current request
        self._asked_with = None  # (send_to, provider) of the current conversation
        self._pump_job = None

        self.win = tk.Toplevel(app.root)
        self.win.withdraw()
        self.win.title("Sidekick")
        self.win.protocol("WM_DELETE_WINDOW", self.hide)
        self.win.bind("<Escape>", lambda _e: self.hide())
        self._build()

    # ------------------------------------------------------------- layout

    def _build(self) -> None:
        text_font = tkfont.nametofont("TkTextFont").copy()
        text_font.configure(size=max(10, int(text_font.cget("size"))))
        bold = tkfont.nametofont("TkDefaultFont").copy()
        bold.configure(weight="bold")
        self._fonts = (text_font, bold)  # keep them alive

        outer = ttk.Frame(self.win, padding=10)
        outer.grid(sticky="nsew")
        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(5, weight=1)

        self.where_label = ttk.Label(outer, text="", font=bold)
        self.where_label.grid(row=0, column=0, sticky="w")
        self.note_label = ttk.Label(outer, text="", wraplength=540, justify="left")
        self.note_label.grid(row=1, column=0, sticky="we", pady=(2, 6))

        # --- what will be sent
        self.send_frame = ttk.LabelFrame(outer, text="", padding=6)
        self.send_frame.grid(row=2, column=0, sticky="we")
        self.send_frame.columnconfigure(0, weight=1)
        self.ctx_text = tk.Text(self.send_frame, height=6, width=66, wrap="word", undo=True, font=text_font)
        self.ctx_text.grid(row=0, column=0, sticky="we")
        ctx_scroll = ttk.Scrollbar(self.send_frame, orient="vertical", command=self.ctx_text.yview)
        ctx_scroll.grid(row=0, column=1, sticky="ns")
        self.ctx_text.configure(yscrollcommand=ctx_scroll.set)

        attach_row = ttk.Frame(self.send_frame)
        attach_row.grid(row=1, column=0, columnspan=2, sticky="we", pady=(6, 0))
        attach_row.columnconfigure(0, weight=1)
        self.attach_label = ttk.Label(attach_row, text="No picture or file attached.")
        self.attach_label.grid(row=0, column=0, sticky="w")
        self.remove_button = ttk.Button(attach_row, text="Remove", command=self.on_remove_attachment)
        self.remove_button.grid(row=0, column=1, padx=(6, 0))
        self.paste_button = ttk.Button(attach_row, text="Paste clipboard", command=self.on_paste_clipboard)
        self.paste_button.grid(row=0, column=2, padx=(6, 0))
        self.attach_button = ttk.Button(attach_row, text="Attach file...", command=self.on_attach_file)
        self.attach_button.grid(row=0, column=3, padx=(6, 0))

        # --- the question
        ask_row = ttk.Frame(outer)
        ask_row.grid(row=3, column=0, sticky="we", pady=(8, 0))
        ask_row.columnconfigure(1, weight=1)
        ttk.Label(ask_row, text="Your question:").grid(row=0, column=0, sticky="w")
        self.question_var = tk.StringVar()
        self.question_entry = ttk.Entry(ask_row, textvariable=self.question_var)
        self.question_entry.grid(row=0, column=1, sticky="we", padx=6)
        self.question_entry.bind("<Return>", lambda _e: self.on_ask())
        self.ask_button = ttk.Button(ask_row, text="Ask", command=self.on_ask)
        self.ask_button.grid(row=0, column=2)

        self.quick_row = ttk.Frame(outer)
        self.quick_row.grid(row=4, column=0, sticky="w", pady=(6, 6))
        self.quick_buttons: list[ttk.Button] = []
        self.rebuild_quick_actions()

        # --- the answer
        answer_frame = ttk.Frame(outer)
        answer_frame.grid(row=5, column=0, sticky="nsew")
        self.answer_frame = answer_frame
        answer_frame.columnconfigure(0, weight=1)
        answer_frame.rowconfigure(0, weight=1)
        self.answer = tk.Text(answer_frame, height=12, width=66, wrap="word", state="disabled", font=text_font)
        self.answer.grid(row=0, column=0, sticky="nsew")
        answer_scroll = ttk.Scrollbar(answer_frame, orient="vertical", command=self.answer.yview)
        answer_scroll.grid(row=0, column=1, sticky="ns")
        self.answer.configure(yscrollcommand=answer_scroll.set)
        # Clicking in the answer lets you select part of it and press Ctrl+C.
        self.answer.bind("<Button-1>", lambda _e: self.answer.focus_set())

        bottom = ttk.Frame(outer)
        bottom.grid(row=6, column=0, sticky="we", pady=(8, 0))
        bottom.columnconfigure(4, weight=1)
        self.copy_button = ttk.Button(bottom, text="Copy answer", command=self.on_copy_answer)
        self.copy_button.grid(row=0, column=0)
        self.paste_back_button = ttk.Button(bottom, text="Paste back", command=self.on_paste_back)
        self.paste_back_button.grid(row=0, column=1, padx=(6, 0))
        self.stop_button = ttk.Button(bottom, text="Stop", command=self.on_stop)
        self.stop_button.grid(row=0, column=2, padx=6)
        self.new_button = ttk.Button(bottom, text="New question", command=self.on_new_question)
        self.new_button.grid(row=0, column=3)
        self.status_label = ttk.Label(bottom, text="", anchor="e", justify="right", wraplength=260)
        self.status_label.grid(row=0, column=4, sticky="e")

        self._update_controls()

    def rebuild_quick_actions(self) -> None:
        for button in self.quick_buttons:
            button.destroy()
        self.quick_buttons = []
        for i, action in enumerate(self.app.settings.quick_actions):
            button = ttk.Button(
                self.quick_row, text=action["label"],
                command=lambda prompt=action["prompt"], label=action["label"]: self.on_ask(
                    prompt, quick=True, label=label),
            )
            button.grid(row=0, column=i, padx=(0, 6))
            self.quick_buttons.append(button)

    # --------------------------------------------------------- show / hide

    @property
    def visible(self) -> bool:
        return self.win.state() != "withdrawn"

    def open(self, capture: Capture) -> None:
        """Start fresh with whatever was just captured, and show the window."""
        self._abandon_request()
        self.conversation = Conversation()
        self.capture = capture
        self.attachment = capture.attachment
        self._attachment_seq = self.app.platform.clipboard_sequence()
        self.last_answer = ""
        self._asked_with = None

        if capture.private:
            where = "Private window (nothing was read)"
        elif capture.window is not None:
            where = "From: " + capture.window.describe()
        else:
            where = "Ask Claude"
        self.where_label.configure(text=where)
        self.note_label.configure(text=capture.note)

        self.ctx_text.configure(state="normal")
        self.ctx_text.delete("1.0", "end")
        if capture.text:
            self.ctx_text.insert("1.0", capture.text)
        self._set_answer("")
        self.question_var.set("")
        self._set_status("")
        self.refresh_mode()
        self._update_controls()

        first_time = not self.visible
        self.win.deiconify()
        if first_time:
            self._place_near_pointer()
        self.focus()

    def refresh_mode(self) -> None:
        """Name the main button after where the question goes. When Claude
        answers in its own app, the answer box and its buttons are hidden."""
        self.ask_button.configure(text=self.app.ask_label())
        if not self.conversation.started:
            self.send_frame.configure(text=f"What will be sent to {self._receiver()} (you can edit or delete it)")
        answers_here = self.app.settings.send_to == "api"
        for widget in (self.answer_frame, self.copy_button, self.paste_back_button, self.stop_button):
            if answers_here:
                widget.grid()
            else:
                widget.grid_remove()

    def _receiver(self) -> str:
        """Who gets the question: Claude (app or website) or the AI service."""
        s = self.app.settings
        return services.service_name(s) if s.send_to == "api" else "Claude"

    def set_note(self, text: str) -> None:
        self.note_label.configure(text=text)

    def focus(self) -> None:
        self.win.lift()
        self.win.attributes("-topmost", True)
        self.win.focus_force()
        self.question_entry.focus_set()

    def hide(self) -> None:
        self._abandon_request()
        self.win.withdraw()

    def _place_near_pointer(self) -> None:
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        px, py = self.win.winfo_pointerxy()
        vx, vy = self.win.winfo_vrootx(), self.win.winfo_vrooty()
        vw, vh = self.win.winfo_vrootwidth(), self.win.winfo_vrootheight()
        if vw <= 1 or vh <= 1:
            vx, vy, vw, vh = 0, 0, self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        x = max(vx + 8, min(px - w // 2, vx + vw - w - 8))
        y = max(vy + 8, min(py - h // 3, vy + vh - h - 60))
        self.win.geometry(f"+{x}+{y}")

    # ------------------------------------------------------ small helpers

    def _set_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def _set_answer(self, text: str) -> None:
        self.answer.configure(state="normal")
        self.answer.delete("1.0", "end")
        if text:
            self.answer.insert("1.0", text)
        self.answer.configure(state="disabled")

    def _append_answer(self, text: str) -> None:
        self.answer.configure(state="normal")
        self.answer.insert("end", text)
        self.answer.configure(state="disabled")
        self.answer.see("end")

    def answer_text(self) -> str:
        return self.answer.get("1.0", "end-1c")

    def context_text(self) -> str:
        return self.ctx_text.get("1.0", "end-1c")

    def _update_controls(self) -> None:
        """Switch buttons on and off to match what can be done right now."""
        def state(on: bool) -> str:
            return "normal" if on else "disabled"

        editable = not self.conversation.started and not self._busy
        self.ctx_text.configure(state=state(editable))
        self.paste_button.configure(state=state(editable))
        self.attach_button.configure(state=state(editable))
        self.remove_button.configure(state=state(editable and self.attachment is not None))
        self.attach_label.configure(
            text=("Attached: " + self.attachment.describe()) if self.attachment else "No picture or file attached."
        )
        for widget in [self.ask_button, self.question_entry, *self.quick_buttons]:
            widget.configure(state=state(not self._busy))
        self.stop_button.configure(state=state(self._busy))
        self.copy_button.configure(state=state(bool(self.last_answer)))
        self.paste_back_button.configure(state=state(bool(self.last_answer) and not self._busy))

    # ------------------------------------------------- attachment buttons

    def on_remove_attachment(self) -> None:
        self.attachment = None
        self._update_controls()

    def on_attach_file(self) -> None:
        path = self.app.dialogs.open_file(self.win)
        if not path:
            return
        if is_pdf(path):
            # A big PDF is read for its text, which can take a few seconds:
            # do it in the background so the window keeps working.
            self._busy = self._reading = True
            self._request_id += 1
            self._stop = threading.Event()
            self._set_status("Reading the PDF...")
            self._update_controls()
            threading.Thread(target=_read_worker, daemon=True, args=(
                self._events, self._request_id, path, self.app.settings.max_image_edge)).start()
            if self._pump_job is None:
                self._pump()
            return
        try:
            self.attachment = attachment_from_path(path, self.app.settings.max_image_edge)
        except AttachmentError as e:
            self.app.dialogs.error(self.win, "Cannot attach this file", str(e))
            return
        self._update_controls()

    def on_paste_clipboard(self) -> None:
        if self.app.platform.clipboard_marked_private() and not self.app.dialogs.confirm(
            self.win, "Private clipboard",
            "The clipboard holds something marked private (it may be a password).\n\nUse it anyway?",
        ):
            return
        text, attachment, note = read_clipboard(
            self.app.read_clipboard_text, self.app.platform.grab_clipboard_media, self.app.settings
        )
        if text:
            self.ctx_text.delete("1.0", "end")
            self.ctx_text.insert("1.0", text)
        if attachment is not None:
            self.attachment = attachment
            self._attachment_seq = self.app.platform.clipboard_sequence()
        self.note_label.configure(text=note)
        self._update_controls()

    # ---------------------------------------------------------------- ask

    def on_ask(self, question: str | None = None, quick: bool = False, label: str = "") -> None:
        """`label`: the button's name, shown above the answer instead of its
        full instruction (for the quick buttons and the one-key hotkey)."""
        if self._busy:
            return
        app = self.app
        question = (question if question is not None else self.question_var.get()).strip()
        first = not self.conversation.started
        text = self.context_text().strip() if first else ""

        if not question:
            self._set_status("Type a question, or click one of the buttons.")
            return
        mode = (app.settings.send_to, app.settings.provider)
        if not first and mode != self._asked_with:
            # The answers so far came from another AI service (or Claude app
            # mode is now on): its history can't be sent to the new one.
            self._set_status("You changed the AI service in Settings. Click New question to ask it.")
            return
        if quick and first and not text and self.attachment is None:
            self._set_status("Copy something first (Ctrl+C) and click Paste clipboard, or type your own question.")
            return
        handoff = app.settings.send_to != "api"  # use the Claude app or website
        if not handoff:
            if not app.has_key():
                name = PROVIDER_NAMES[app.settings.provider].replace(" API", "")
                app.open_settings(
                    f"To show answers from {name} inside Sidekick, it needs an API key. Paste it below, "
                    "or choose another AI service: Claude Code and Ollama need no key."
                )
                return
            limit = app.settings.daily_limit_usd
            spent = app.spend.today_total()
            if limit > 0 and spent >= limit and services.counts_spending(app.settings):
                app.dialogs.info(
                    self.win, "Daily limit reached",
                    f"Today's estimated spending ({format_money(spent)}) has reached your daily limit "
                    f"of ${limit:.2f}.\n\nYou can raise the limit in Settings.",
                )
                return

        if first:
            if len(text) > app.settings.max_text_chars:
                app.dialogs.info(
                    self.win, "Too much text",
                    f"The box holds {len(text):,} characters; the most Sidekick sends is "
                    f"{app.settings.max_text_chars:,}.\n\nDelete the parts you do not need.",
                )
                return
            secrets = find_secrets(text + "\n" + question)
            if secrets and not app.dialogs.confirm(
                self.win, "This may contain a secret",
                "The text you are about to send looks like it contains "
                + " and ".join(secrets)
                + f".\n\nSend it to {self._receiver()} anyway?",
            ):
                return
            window = self.capture.window if (app.settings.send_window_title and not self.capture.private) else None
            if handoff:
                self._hand_off(question, text, window)
                return
            content: object = build_first_message(question, text, window, self.attachment)
            needs_count = (app.settings.provider == "claude"  # only Claude can count tokens first
                           and self.attachment is not None and self.attachment.kind in ("pdf", "text"))
        else:
            content = build_followup_message(question)
            needs_count = False

        # Show the question above its answer (the question box is cleared later).
        lead = "\n\n" if self.answer_text().strip() else ""
        self._append_answer(f"{lead}You asked: {label or question}\n\n")

        self._busy = True
        self._asked_with = mode
        self._got_text = False
        self._request_id += 1
        self._stop = threading.Event()
        self._pending = (question, content)
        self._client = app.client()  # made here, on the window's own thread
        self._update_controls()
        if needs_count:
            self._set_status("Checking the size...")
            self._run_in_background(_count_worker, self._client, self.conversation, content)
        else:
            self._start_streaming(content)
        if self._pump_job is None:
            self._pump()

    def _hand_off(self, question: str, text: str, window) -> None:
        """Open a new Claude chat (app or website) with the question filled in."""
        app = self.app
        attachment = self.attachment
        picture_on_clipboard = False
        if attachment is not None and attachment.kind == "image" and not attachment.path:
            # A snipped picture: still on the clipboard unless something else was copied since.
            picture_on_clipboard = app.platform.clipboard_sequence() == self._attachment_seq
            if not picture_on_clipboard:
                try:
                    save_to_temp_file(attachment)  # so it can be dragged into Claude instead
                except OSError as e:
                    app.dialogs.error(self.win, "Could not prepare the picture", f"The picture could not be saved ({e}).")
                    return
        prompt = build_chat_prompt(question, text, window, attachment)
        if app.hand_off(prompt, attachment, picture_on_clipboard):
            self.hide()

    def _run_in_background(self, target, *args) -> None:
        # The thread gets only plain objects (the queue, the Claude client,
        # the conversation): never a window. Tk windows must only ever be
        # touched, or freed, by the thread that created them.
        threading.Thread(target=target, args=(self._events, self._request_id, *args), daemon=True).start()

    def _start_streaming(self, content: object) -> None:
        self._set_status("Thinking...")
        self._run_in_background(_ask_worker, self._client, content, self.conversation, self._stop)

    def _pump(self) -> None:
        """Move replies from the background thread onto the screen."""
        self._pump_job = None
        try:
            while True:
                rid, kind, payload = self._events.get_nowait()
                if rid != self._request_id:
                    continue  # from a request that was stopped or replaced
                if kind == "text":
                    if not self._got_text:
                        self._got_text = True
                        self._set_status("Writing...")
                    self._append_answer(payload)
                elif kind == "count":
                    self._on_counted(payload)
                elif kind == "attached":
                    self._reading = False
                    self.attachment = payload
                    self._finish("")
                elif kind == "attach_error":
                    self._reading = False
                    self._finish("")
                    self.app.dialogs.error(self.win, "Cannot attach this file", payload)
                elif kind == "done":
                    self._on_done(payload)
                elif kind == "error":
                    self._on_error(payload)
        except queue.Empty:
            pass
        if self._busy and self._pump_job is None:
            self._pump_job = self.win.after(30, self._pump)

    def _on_counted(self, tokens: int | None) -> None:
        app = self.app
        _question, content = self._pending
        go = True
        if tokens is None:
            if self.attachment is not None and self.attachment.kind == "pdf":
                go = app.dialogs.confirm(
                    self.win, "Size unknown",
                    "Sidekick could not check how big this PDF is. Long PDFs can cost a lot to send.\n\nSend it anyway?",
                )
        else:
            cost = input_cost(app.settings.model, tokens)
            threshold = app.settings.confirm_cost_usd
            if cost is not None and threshold > 0 and cost > threshold:
                go = app.dialogs.confirm(
                    self.win, "This is a big request",
                    f"This will send about {tokens:,} tokens to Claude. That costs about "
                    f"{format_money(cost)} before the answer.\n\nSend it?",
                )
        if go:
            self._start_streaming(content)
        else:
            self._append_answer("[Not sent]")
            self._finish("Not sent.")

    def _finish(self, status: str) -> None:
        self._busy = False
        self._set_status(status)
        self._update_controls()

    def _on_done(self, result: AskResult) -> None:
        app = self.app
        if result.cancelled:
            self._finish("Stopped.")
            return
        total = app.spend.add(result.cost_usd)
        app.refresh_main()
        if result.notice:
            self._append_answer(("\n\n" if self.answer_text().strip() else "") + f"[{result.notice}]")
        if not result.refused:
            self.last_answer = result.text
            self.question_var.set("")
            self.send_frame.configure(text="Sent with your first question")
        status = services.short_label(app.settings, result.model)
        if result.cost_usd is not None:
            status += f" \u00b7 about {format_money(result.cost_usd)} \u00b7 today {format_money(total)}"
        elif app.settings.provider == "ollama":
            status += " \u00b7 free, on this PC"
        self._finish(status)
        self.question_entry.focus_set()

    def _on_error(self, error: AskError) -> None:
        self._append_answer(("\n\n" if self.answer_text().strip() else "") + f"[Problem] {error}")
        self._finish("Not answered.")
        if error.needs_key:
            self.app.open_settings(str(error))

    def _abandon_request(self) -> None:
        """Stop listening to the current request (if any)."""
        self._stop.set()
        self._request_id += 1
        self._busy = self._reading = False
        if self._pump_job is not None:
            try:
                self.win.after_cancel(self._pump_job)
            except tk.TclError:
                pass  # the window is already gone
            self._pump_job = None

    def on_stop(self) -> None:
        if not self._busy:
            return
        reading, self._reading = self._reading, False
        self._abandon_request()
        if reading:
            self._finish("Stopped reading the file.")
            return
        self._append_answer("\n[Stopped]")
        self._finish("Stopped.")

    def on_new_question(self) -> None:
        self.open(Capture(window=self.capture.window, private=self.capture.private,
                          note="Started a new question. Paste or attach what you want to ask about."))

    def auto_ask(self, prompt: str, label: str = "") -> None:
        """One-key mode: ask right away, as if a quick button was clicked."""
        self.on_ask(prompt, quick=True, label=label)

    def on_paste_back(self) -> None:
        if self.last_answer and not self._busy:
            self.app.paste_back(self.last_answer, self.capture.window)

    def on_copy_answer(self) -> None:
        if not self.last_answer:
            return
        root = self.app.root
        root.clipboard_clear()
        root.clipboard_append(self.last_answer)
        root.update_idletasks()
        self.app.watch.note_own_copy(self.last_answer)
        self._set_status("Copied. Press Ctrl+V in your app to paste.")
