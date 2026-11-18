"""End-to-end tests of the real Sidekick windows.

Each test opens the actual main window and Ask popup (on a virtual screen
when run with xvfb-run), clicks through them like a person would, and
checks what was sent to a fake Claude server running on this computer.
Windows itself is replaced by FakePlatform, and the system key store by
FakeKeyring, so no real hotkey, clipboard watcher, API key or internet is used.
"""

import gc
import json
import os
import sys
import time
import urllib.parse

import pytest

tk = pytest.importorskip("tkinter")
Image = pytest.importorskip("PIL.Image")

from fake_api import FakeAnthropic, api_error, sse_events  # noqa: E402
from fake_compat import FakeCompat, chunks  # noqa: E402
from sidekick import keystore, services  # noqa: E402
from sidekick.app import SidekickApp  # noqa: E402
from sidekick.capture import TIP  # noqa: E402
from sidekick.config import SMART_PROMPT  # noqa: E402
from sidekick.config import Settings, load_settings  # noqa: E402
from sidekick.costs import DailySpend  # noqa: E402
from sidekick.platform_base import Platform, WindowInfo  # noqa: E402
from sidekick.popup import Dialogs  # noqa: E402

EXCEL = WindowInfo("Budget.xlsx - Excel", "excel.exe", 4321, hwnd=4321)
WORD = WindowInfo("Letter.docx - Word", "winword.exe", 4322, hwnd=4322)
BITWARDEN = WindowInfo("My vault - Bitwarden", "bitwarden.exe", 555)
FAKE_CLAUDE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_claude.py")
# The settings the older tests were written for: answers inside Sidekick from
# the Claude API, and the hotkey only opens the window.
API = dict(send_to="api", provider="claude", instant=False)


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, service, account):
        return self.store.get((service, account))

    def set_password(self, service, account, value):
        self.store[(service, account)] = value

    def delete_password(self, service, account):
        self.store.pop((service, account), None)


class FakePlatform(Platform):
    name = "fake"

    def __init__(self):
        self.seq = 1
        self.private = False
        self.media = None
        self.started = []
        self.stops = 0
        self.taken = set()
        self.app_installed = True
        self.link_ok = True
        self.chrome_ok = True
        self.opened = []  # (how, link)
        self.revealed = []
        self.selection = None  # text "selected" in the app in front, for one-key mode
        self.copy_calls = []
        self.on_copy = None  # set by the Harness: puts text on the clipboard
        self.pasted = []
        self.paste_ok = True

    def start_hotkey(self, hotkey, on_press):
        if str(hotkey) in self.taken:
            return False, "in_use"
        self.started.append(str(hotkey))
        return True, ""

    def stop_hotkey(self):
        self.stops += 1

    def clipboard_sequence(self):
        return self.seq

    def clipboard_marked_private(self):
        return self.private

    def grab_clipboard_media(self):
        return self.media

    def claude_app_installed(self):
        return self.app_installed

    def open_link(self, url):
        if not self.link_ok or (url.startswith("claude:") and not self.app_installed):
            return False
        self.opened.append(("link", url))
        return True

    def open_in_chrome(self, url):
        if not self.chrome_ok:
            return False
        self.opened.append(("chrome", url))
        return True

    def reveal_file(self, path):
        self.revealed.append(path)
        return True

    def copy_selection(self, window):
        self.copy_calls.append(window)
        if self.selection is None:
            return False
        self.on_copy(self.selection)
        return True

    def paste_into(self, window):
        self.pasted.append(window)
        return self.paste_ok


class FakeDialogs(Dialogs):
    def __init__(self):
        self.calls = []
        self.answer = True  # what "Yes/No" questions are answered with
        self.file = ""  # what the "Attach a file" box returns

    def info(self, parent, title, message):
        self.calls.append(("info", title, message))

    def error(self, parent, title, message):
        self.calls.append(("error", title, message))

    def confirm(self, parent, title, message):
        self.calls.append(("confirm", title, message))
        return self.answer

    def open_file(self, parent):
        return self.file

    def titles(self, kind):
        return [title for k, title, _ in self.calls if k == kind]


class Harness:
    """Starts Sidekick with fakes around it and offers 'user actions'."""

    def __init__(self, tmp_path, monkeypatch, api, settings=None, platform=None):
        self.keyring = FakeKeyring()
        monkeypatch.setattr(keystore, "_keyring", lambda: self.keyring)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        try:
            self.root = tk.Tk()
        except tk.TclError:
            pytest.skip("no screen available (run the tests with xvfb-run)")
        self.api = api
        self.platform = platform or FakePlatform()
        self.dialogs = FakeDialogs()
        self.settings_path = tmp_path / "config.json"
        self.spend = DailySpend(tmp_path / "usage.json")
        self.platform.on_copy = self.copy
        self.app = SidekickApp(
            self.root, self.platform, settings or Settings(**API), self.spend,
            settings_path=self.settings_path, dialogs=self.dialogs,
            client_factory=lambda s: services.make_client(
                s, claude_kwargs={"base_url": api.base_url, "max_retries": 0},
                claude_code_command=[sys.executable, FAKE_CLAUDE]),
        )
        self.errors = []
        self.root.report_callback_exception = lambda *exc: self.errors.append(exc)
        self.popup = self.app.popup
        self.pump()

    # -- driving the windows

    def pump(self, seconds=0.05):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            time.sleep(0.005)

    def wait(self, condition, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            self.root.update()
            if condition():
                return
            time.sleep(0.01)
        raise AssertionError("timed out waiting for the window")

    def set_key(self, key="sk-ant-test"):
        self.keyring.set_password(keystore.SERVICE, keystore.ACCOUNT, key)
        self.app.on_key_changed()

    def copy(self, text):
        """What pressing Ctrl+C in another app does."""
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()
        self.platform.seq += 1

    def clear_clipboard(self):
        self.root.clipboard_clear()
        self.root.update()
        self.platform.seq += 1

    def press_hotkey(self, window=EXCEL):
        self.app._on_hotkey(window)  # what the hotkey thread does
        self.app.process_events()
        self.pump()

    def ask(self, question):
        self.popup.question_var.set(question)
        self.popup.ask_button.invoke()
        self.wait(lambda: not self.popup._busy)

    # -- reading the windows

    def label(self, widget):
        return str(widget.cget("text"))

    def sent_text(self, index=-1):
        """The words part of the first message of request number `index`."""
        content = self.api.requests[index]["body"]["messages"][0]["content"]
        return content[-1]["text"]

    def close(self):
        # Let a request that is still running finish, so its thread is done.
        try:
            self.wait(lambda: not self.popup._busy, timeout=5)
        except (AssertionError, tk.TclError):
            pass
        try:
            # Hand the keyboard focus back to the main window first: Tk can
            # crash later, in the next test's windows, if a closed dialog
            # still owned it when its program ended.
            self.root.focus_force()
            self.root.update()
        except tk.TclError:
            pass
        try:
            self.app.quit()  # cancels timers, releases the hotkey, closes windows
        except tk.TclError:
            pass  # already closed by the test
        # Free every window object now, on this (the main) thread. Tk objects
        # freed from any other thread can crash the Tcl library.
        self.app = self.popup = self.root = None
        gc.collect()


@pytest.fixture
def api():
    server = FakeAnthropic().start()
    yield server
    server.stop()


@pytest.fixture
def h(tmp_path, monkeypatch, api):
    harness = Harness(tmp_path, monkeypatch, api)
    yield harness
    errors = list(harness.errors)
    harness.close()
    assert errors == [], f"the window code raised: {errors}"


# ---------------------------------------------------------------- main window


def test_main_window_explains_what_to_do(h):
    assert h.platform.started == ["ctrl+shift+space"]
    assert "Press Ctrl+Shift+Space" in h.label(h.app.howto_label)
    assert h.label(h.app.hotkey_label) == "Hotkey: Ctrl+Shift+Space"
    assert "not set yet" in h.label(h.app.key_label)
    assert h.label(h.app.spend_label) == "Spent today: $0.00 of your $2.00 daily limit"


def test_backup_hotkey_when_the_first_is_taken(tmp_path, monkeypatch, api):
    platform = FakePlatform()
    platform.taken = {"ctrl+shift+space"}
    harness = Harness(tmp_path, monkeypatch, api, platform=platform)
    try:
        assert platform.started == ["ctrl+alt+shift+space"]
        text = harness.label(harness.app.hotkey_label)
        assert text.startswith("Hotkey: Ctrl+Alt+Shift+Space")
        assert "already used by another app" in text
    finally:
        harness.close()


def test_no_hotkey_when_both_are_taken(tmp_path, monkeypatch, api):
    platform = FakePlatform()
    platform.taken = {"ctrl+shift+space", "ctrl+alt+shift+space"}
    harness = Harness(tmp_path, monkeypatch, api, platform=platform)
    try:
        assert harness.app.active_hotkey is None
        assert "Ask now button" in harness.label(harness.app.hotkey_label)
        assert "Click the Ask now button" in harness.label(harness.app.howto_label)
    finally:
        harness.close()


# ------------------------------------------------------------------- asking


def test_ask_about_copied_text(h):
    h.set_key()
    h.copy("=SUM(A1:A3")
    h.press_hotkey(EXCEL)

    assert h.popup.visible
    assert h.label(h.popup.where_label) == "From: Excel — Budget.xlsx - Excel"
    assert h.popup.context_text() == "=SUM(A1:A3"
    assert "Nothing is sent until you say so" in h.label(h.popup.note_label)
    assert h.api.requests == []  # nothing is sent before Ask

    h.api.script.append(sse_events(["Add the missing", " bracket:\n=SUM(A1:A3)"]))
    h.ask("Why is this formula wrong?")

    assert h.popup.answer_text() == (
        "You asked: Why is this formula wrong?\n\nAdd the missing bracket:\n=SUM(A1:A3)"
    )
    text = h.sent_text()
    assert "<active_window>\napp: Excel\ntitle: Budget.xlsx - Excel\n</active_window>" in text
    assert "<copied_text>\n=SUM(A1:A3\n</copied_text>" in text
    assert text.endswith("<question>\nWhy is this formula wrong?\n</question>")
    assert h.label(h.popup.status_label).startswith("Opus 5.5 · about ")
    assert h.spend.today_total() > 0
    assert "Spent today: about" in h.label(h.app.spend_label)
    # the first message is fixed now; follow-ups build on it
    assert str(h.popup.ctx_text.cget("state")) == "disabled"
    assert h.label(h.popup.send_frame) == "Sent with your first question"

    h.popup.copy_button.invoke()
    assert h.root.clipboard_get() == "Add the missing bracket:\n=SUM(A1:A3)"
    assert "Ctrl+V" in h.label(h.popup.status_label)

    # Pressing the hotkey again does not pick up Sidekick's own answer.
    h.press_hotkey(EXCEL)
    assert h.popup.context_text() == ""
    assert h.label(h.popup.note_label) == TIP


def test_follow_up_question(h):
    h.set_key()
    h.copy("Hola, ¿cómo estás?")
    h.press_hotkey(EXCEL)
    h.api.script.append(sse_events(["It means: Hello, how are you?"]))
    h.ask("Translate this")
    h.api.script.append(sse_events(["Reply: Estoy bien, gracias."]))
    h.ask("How do I answer?")

    messages = h.api.requests[1]["body"]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[2]["content"] == "How do I answer?"
    shown = h.popup.answer_text()
    assert shown.startswith("You asked: Translate this\n\nIt means: Hello, how are you?")
    assert "\n\nYou asked: How do I answer?\n\n" in shown
    assert shown.endswith("Reply: Estoy bien, gracias.")


def test_typed_question_without_copying(h):
    h.set_key()
    h.press_hotkey(EXCEL)
    assert h.label(h.popup.note_label) == TIP
    h.ask("What is the shortcut to undo?")
    text = h.sent_text()
    assert "<copied_text>" not in text
    assert "<active_window>" in text


def test_private_window_reads_and_sends_nothing(h):
    h.set_key()
    h.copy("hunter2")
    h.press_hotkey(BITWARDEN)
    assert h.label(h.popup.where_label) == "Private window (nothing was read)"
    assert h.popup.context_text() == ""
    h.ask("How do I make a strong password?")
    text = h.sent_text()
    assert "hunter2" not in text and "Bitwarden" not in text and "<active_window>" not in text


def test_window_title_can_be_switched_off(tmp_path, monkeypatch, api):
    harness = Harness(tmp_path, monkeypatch, api, settings=Settings(**API, send_window_title=False))
    try:
        harness.set_key()
        harness.press_hotkey(EXCEL)
        harness.ask("Hi")
        assert "<active_window>" not in harness.sent_text()
    finally:
        harness.close()


def test_secret_warning_lets_you_cancel(h):
    h.set_key()
    h.copy("server login\npassword: hunter2")
    h.press_hotkey(EXCEL)
    h.dialogs.answer = False
    h.ask("Is this a strong password?")
    assert h.dialogs.titles("confirm") == ["This may contain a secret"]
    assert h.api.requests == []
    assert str(h.popup.ask_button.cget("state")) == "normal"

    h.dialogs.answer = True
    h.ask("Is this a strong password?")
    assert len(h.api.requests) == 1


def test_daily_limit_stops_sending(h):
    h.set_key()
    h.spend.add(5.0)
    h.press_hotkey(EXCEL)
    h.ask("Hi")
    assert h.dialogs.titles("info") == ["Daily limit reached"]
    assert h.api.requests == []


def test_missing_key_opens_settings_and_key_can_be_saved(h):
    h.press_hotkey(EXCEL)
    h.ask("Hi")
    assert h.api.requests == []
    dialog = h.app.settings_dialog
    assert dialog is not None and dialog.alive
    assert "No key saved" in h.label(dialog.key_status)

    dialog.key_var.set("sk-ant-new-key")
    dialog.on_save_key()
    assert h.keyring.get_password(keystore.SERVICE, keystore.ACCOUNT) == "sk-ant-new-key"
    assert dialog.key_var.get() == ""  # the box is cleared after saving
    assert h.label(h.app.key_label).endswith("API key: saved")


def test_odd_looking_key_is_double_checked(h):
    h.app.open_settings()
    dialog = h.app.settings_dialog
    dialog.key_var.set("hello")
    h.dialogs.answer = False
    dialog.on_save_key()
    assert h.dialogs.titles("confirm") == ["Check the key"]
    assert h.keyring.store == {}


def test_rejected_key_is_explained(h):
    h.set_key("sk-ant-wrong")
    h.api.script.append(api_error(401, "authentication_error", "invalid x-api-key"))
    h.press_hotkey(EXCEL)
    h.ask("Hi")
    assert "[Problem] Your API key was not accepted" in h.popup.answer_text()
    assert h.label(h.popup.status_label) == "Not answered."
    assert h.app.settings_dialog is not None and h.app.settings_dialog.alive


def test_stop_button(h):
    h.set_key()
    h.api.event_delay = 0.03
    h.api.script.append(sse_events([f"part{i} " for i in range(60)]))
    h.press_hotkey(EXCEL)
    h.popup.question_var.set("Write a long story")
    h.popup.ask_button.invoke()
    h.wait(lambda: "part1 " in h.popup.answer_text())
    h.popup.stop_button.invoke()
    assert h.label(h.popup.status_label) == "Stopped."
    shown = h.popup.answer_text()
    h.pump(0.5)
    assert h.popup.answer_text() == shown  # nothing more arrives after Stop
    assert shown.endswith("[Stopped]") and "part59" not in shown
    assert h.popup.conversation.messages == []

    h.api.event_delay = 0
    h.api.script.append(sse_events(["Short one."]))
    h.ask("A short story then")
    assert h.popup.answer_text().endswith("Short one.")


def test_quick_buttons(h):
    h.set_key()
    h.press_hotkey(EXCEL)
    h.popup.quick_buttons[0].invoke()  # "Explain" with nothing to explain
    assert "Copy something first" in h.label(h.popup.status_label)
    assert h.api.requests == []

    h.copy("Photosynthesis converts light energy into chemical energy.")
    h.press_hotkey(EXCEL)
    h.popup.quick_buttons[0].invoke()
    h.wait(lambda: not h.popup._busy)
    assert h.sent_text().endswith("<question>\nExplain this in simple words.\n</question>")


def test_attach_text_file_checks_size_first(h, tmp_path):
    h.set_key()
    h.press_hotkey(EXCEL)
    notes = tmp_path / "notes.txt"
    notes.write_text("Agenda: budget, hiring, travel.", encoding="utf-8")
    h.dialogs.file = str(notes)
    h.popup.attach_button.invoke()
    assert h.label(h.popup.attach_label) == "Attached: File: notes.txt (1 KB)"

    h.ask("Summarize")
    assert len(h.api.count_requests) == 1
    assert '<file name="notes.txt">\nAgenda: budget, hiring, travel.\n</file>' in h.sent_text()


def test_big_pdf_asks_before_sending(h, tmp_path):
    h.set_key()
    h.press_hotkey(EXCEL)
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4\n% pretend this is a long report\n")
    h.dialogs.file = str(pdf)
    h.popup.attach_button.invoke()
    h.api.count_reply = {"input_tokens": 200_000}  # about $0.80 to send

    h.dialogs.answer = False
    h.ask("Summarize this report")
    assert h.dialogs.titles("confirm") == ["This is a big request"]
    assert "about 80¢" in h.dialogs.calls[-1][2]
    assert h.label(h.popup.status_label) == "Not sent."
    assert h.popup.answer_text().endswith("[Not sent]")
    assert h.api.requests == []

    h.dialogs.answer = True
    h.ask("Summarize this report")
    content = h.api.requests[0]["body"]["messages"][0]["content"]
    assert content[0]["type"] == "document"


def test_snipped_picture_is_attached(h):
    h.set_key()
    h.clear_clipboard()
    h.platform.media = Image.new("RGB", (3000, 1500), "white")
    h.press_hotkey(EXCEL)
    assert h.label(h.popup.attach_label) == "Attached: Picture (1920 x 960)"
    h.ask("What is in this picture?")
    content = h.api.requests[0]["body"]["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/png"
    assert h.api.requests[0]["body"]["cache_control"] == {"type": "ephemeral"}


def test_remove_attachment_and_new_question(h):
    h.set_key()
    h.clear_clipboard()
    h.platform.media = Image.new("RGB", (100, 100))
    h.press_hotkey(EXCEL)
    h.popup.remove_button.invoke()
    assert h.label(h.popup.attach_label) == "No picture or file attached."
    h.ask("Hello")
    assert h.api.requests[0]["body"]["messages"][0]["content"][0]["type"] == "text"

    h.popup.new_button.invoke()
    assert not h.popup.conversation.started
    assert h.popup.answer_text() == ""
    assert str(h.popup.ctx_text.cget("state")) == "normal"


def test_hotkey_pressed_inside_sidekick_keeps_your_work(h):
    h.set_key()
    h.copy("abc")
    h.press_hotkey(EXCEL)
    h.popup.ctx_text.delete("1.0", "end")
    h.popup.ctx_text.insert("1.0", "my edited text")
    h.press_hotkey(WindowInfo("Sidekick", "python.exe", os.getpid()))
    assert h.popup.context_text() == "my edited text"


# ------------------------------------------------------------------ settings


def test_settings_are_saved_and_used(h):
    h.app.open_settings()
    dialog = h.app.settings_dialog
    dialog.model_box.current(1)  # Sonnet 5.5
    dialog.effort_box.current(0)  # low
    dialog.hotkey_var.set("Ctrl + Alt + K")
    dialog.limit_var.set("$3")
    dialog.title_var.set(False)
    dialog.on_save()

    saved = load_settings(h.settings_path)
    assert (saved.send_to, saved.model, saved.effort, saved.hotkey, saved.daily_limit_usd, saved.send_window_title) == (
        "api", "claude-sonnet-5-5", "low", "ctrl+alt+k", 3.0, False)
    assert h.platform.started[-1] == "ctrl+alt+k"
    assert h.label(h.app.hotkey_label) == "Hotkey: Ctrl+Alt+K"
    assert not dialog.alive

    h.set_key()
    h.press_hotkey(EXCEL)
    h.api.script.append(sse_events(["ok"], model="claude-sonnet-5-5"))
    h.ask("Hi")
    body = h.api.requests[0]["body"]
    assert body["model"] == "claude-sonnet-5-5"
    assert body["output_config"] == {"effort": "low"}
    assert "<active_window>" not in h.sent_text()
    assert h.label(h.popup.status_label).startswith("Sonnet 5.5")


def test_settings_reject_bad_input(h):
    h.app.open_settings()
    dialog = h.app.settings_dialog
    dialog.hotkey_var.set("shift+a")
    dialog.on_save()
    assert h.dialogs.titles("error") == ["Hotkey"]
    assert dialog.alive and not h.settings_path.exists()

    dialog.hotkey_var.set("ctrl+shift+space")
    dialog.limit_var.set("lots")
    dialog.on_save()
    assert h.dialogs.titles("error") == ["Hotkey", "Daily limit"]
    assert not h.settings_path.exists()


def test_closing_the_main_window(h):
    h.dialogs.answer = False  # "No: keep it running"
    h.app.on_close()
    assert h.root.winfo_exists()
    h.dialogs.answer = True  # "Yes: quit"
    h.app.on_close()
    assert h.platform.stops >= 1
    with pytest.raises(tk.TclError):
        h.root.winfo_exists()


# ------------------------------------- "use my Claude plan" (no API key)


def q_of(url):
    """The question carried inside a claude.ai link, decoded."""
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("q", [None])[0]


@pytest.fixture
def ho(tmp_path, monkeypatch, api):
    """Sidekick with its default setting: questions open in the Claude app."""
    harness = Harness(tmp_path, monkeypatch, api, settings=Settings(send_to="claude_app", instant=False))
    yield harness
    errors = list(harness.errors)
    harness.close()
    assert errors == [], f"the window code raised: {errors}"


def open_in_claude(harness, question):
    harness.popup.question_var.set(question)
    harness.popup.ask_button.invoke()
    harness.pump()


def test_default_opens_the_claude_app_with_no_key(ho):
    assert ho.app.settings.send_to == "claude_app"
    assert "uses your Claude plan" in ho.label(ho.app.key_label)
    assert ho.label(ho.app.spend_label) == ""
    assert "click Open in Claude" in ho.label(ho.app.howto_label)

    ho.copy("=SUM(A1:A3")
    ho.press_hotkey(EXCEL)
    assert str(ho.popup.ask_button.cget("text")) == "Open in Claude"
    # Claude answers in its own window, so Sidekick's answer box is hidden
    assert ho.popup.ask_button.winfo_ismapped()
    assert not ho.popup.answer_frame.winfo_ismapped()
    assert not ho.popup.copy_button.winfo_ismapped()
    open_in_claude(ho, "Why is this formula wrong?")

    assert ho.api.requests == []  # the API is not used at all
    assert ho.app.settings_dialog is None  # and no key is asked for
    (how, url), = ho.platform.opened
    assert how == "link" and url.startswith("claude://claude.ai/new?q=")
    assert q_of(url) == (
        'I am working in Excel, in the window "Budget.xlsx - Excel".\n\n'
        'Here is what I copied:\n"""\n=SUM(A1:A3\n"""\n\nWhy is this formula wrong?'
    )
    assert not ho.popup.visible
    assert ho.root.clipboard_get() == "=SUM(A1:A3"  # your clipboard is left alone
    assert ho.app.toast is not None
    assert ho.app.toast_text == "Claude is opening in the Claude app. Then:\n1. Check the question, then press Enter."


def test_long_text_goes_through_the_clipboard(ho):
    long_text = "word " * 600
    ho.copy(long_text)
    ho.press_hotkey(EXCEL)
    ho.popup.quick_buttons[2].invoke()  # Summarize
    ho.pump()

    (how, url), = ho.platform.opened
    assert url == "claude://claude.ai/new"
    pasted = ho.root.clipboard_get()
    assert long_text.strip() in pasted
    assert pasted.endswith("Summarize this in a few short points.")
    assert "1. Press Ctrl+V to paste your question." in ho.app.toast_text
    # Sidekick's own copy is not picked up as "just copied" next time
    ho.press_hotkey(EXCEL)
    assert ho.popup.context_text() == ""


def test_snipped_picture_is_pasted_into_claude(ho):
    ho.clear_clipboard()
    ho.platform.media = Image.new("RGB", (800, 600), "white")
    ho.press_hotkey(EXCEL)
    open_in_claude(ho, "What does this chart show?")

    (how, url), = ho.platform.opened
    assert q_of(url).endswith("What does this chart show?")
    assert "Press Ctrl+V to add your picture." in ho.app.toast_text
    assert ho.platform.revealed == []


def test_picture_no_longer_on_the_clipboard_is_offered_as_a_file(ho):
    ho.clear_clipboard()
    ho.platform.media = Image.new("RGB", (800, 600), "white")
    ho.press_hotkey(EXCEL)
    ho.platform.seq += 1  # something else was copied in the meantime
    open_in_claude(ho, "What does this chart show?")

    path, = ho.platform.revealed
    assert path.endswith("Sidekick picture.png") and os.path.exists(path)
    assert 'Drag "Sidekick picture.png" from the File Explorer window into Claude.' in ho.app.toast_text


def test_attached_pdf_is_shown_in_file_explorer(ho, tmp_path):
    ho.press_hotkey(EXCEL)
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    ho.dialogs.file = str(pdf)
    ho.popup.attach_button.invoke()
    open_in_claude(ho, "Summarize this report")

    assert ho.platform.revealed == [str(pdf)]
    assert 'Drag "report.pdf" from the File Explorer window into Claude.' in ho.app.toast_text
    assert ho.api.count_requests == []  # no size check: nothing goes to the API


def test_chrome_mode_uses_the_website_and_the_clipboard(tmp_path, monkeypatch, api):
    harness = Harness(tmp_path, monkeypatch, api, settings=Settings(send_to="chrome", instant=False))
    try:
        assert "the Claude website in Chrome" in harness.label(harness.app.key_label)
        harness.copy("Bonjour tout le monde")
        harness.press_hotkey(EXCEL)
        open_in_claude(harness, "Translate this")
        assert harness.platform.opened == [("chrome", "https://claude.ai/new")]
        assert harness.root.clipboard_get().endswith("Translate this")
        toast = harness.app.toast_text
        assert toast.startswith("Claude is opening in Chrome. Then:")
        assert "1. Press Ctrl+V to paste your question." in toast
    finally:
        harness.close()


def test_without_the_claude_app_the_website_is_used(ho):
    ho.platform.app_installed = False
    ho.press_hotkey(EXCEL)
    open_in_claude(ho, "Hello")
    assert ho.platform.opened == [("chrome", "https://claude.ai/new")]
    assert ho.app.toast_text.startswith("The Claude app is not installed")


def test_without_chrome_the_usual_browser_is_used(tmp_path, monkeypatch, api):
    harness = Harness(tmp_path, monkeypatch, api, settings=Settings(send_to="chrome", instant=False))
    try:
        harness.platform.chrome_ok = False
        harness.press_hotkey(EXCEL)
        open_in_claude(harness, "Hello")
        assert harness.platform.opened == [("link", "https://claude.ai/new")]
        assert "Chrome was not found" in harness.app.toast_text
        assert "Claude is opening in your web browser" in harness.app.toast_text
    finally:
        harness.close()


def test_when_nothing_opens_the_question_is_copied(ho):
    ho.platform.app_installed = False
    ho.platform.chrome_ok = False
    ho.platform.link_ok = False
    ho.press_hotkey(EXCEL)
    open_in_claude(ho, "Hello")
    assert ho.dialogs.titles("error") == ["Could not open Claude"]
    assert ho.root.clipboard_get().endswith("Hello")
    assert ho.popup.visible  # the window stays, so nothing is lost


def test_private_window_is_left_out_of_the_question(ho):
    ho.copy("hunter2")
    ho.press_hotkey(BITWARDEN)
    open_in_claude(ho, "How do I make a strong password?")
    (how, url), = ho.platform.opened
    assert q_of(url) == "How do I make a strong password?"


def test_secret_warning_also_applies_before_opening_claude(ho):
    ho.copy("password: hunter2")
    ho.press_hotkey(EXCEL)
    ho.dialogs.answer = False
    open_in_claude(ho, "Is this strong?")
    assert ho.dialogs.titles("confirm") == ["This may contain a secret"]
    assert ho.platform.opened == []


def test_switching_to_answers_inside_sidekick(ho):
    ho.app.open_settings()
    dialog = ho.app.settings_dialog
    dialog.send_to_box.current(2)  # "Answer inside Sidekick"
    dialog.on_save()
    assert ho.app.settings.send_to == "api"
    assert load_settings(ho.settings_path).send_to == "api"
    # the default AI service needs no API key: Claude Code with your Claude plan
    assert "from Claude Code on this PC" in ho.label(ho.app.key_label)
    ho.press_hotkey(EXCEL)
    assert str(ho.popup.ask_button.cget("text")) == "Ask"
    assert ho.popup.answer_frame.winfo_ismapped()  # answers show in Sidekick again


# --------------------------------------- one key: select, press, get the answer

import contextlib  # noqa: E402


@pytest.fixture
def compat():
    server = FakeCompat().start()
    yield server
    server.stop()


@contextlib.contextmanager
def started(tmp_path, monkeypatch, api, **settings):
    harness = Harness(tmp_path, monkeypatch, api, settings=Settings(**settings))
    try:
        yield harness
        assert harness.errors == [], f"the window code raised: {harness.errors}"
    finally:
        harness.close()


def press_and_wait(h, window=WORD, selection="Ths sentense has erors."):
    h.platform.selection = selection
    h.press_hotkey(window)
    h.wait(lambda: not h.popup._busy)


def test_one_key_answer_with_the_claude_api(tmp_path, monkeypatch, api):
    with started(tmp_path, monkeypatch, api, send_to="api", provider="claude") as h:
        h.set_key()
        api.script.append(sse_events(["This sentence has errors."]))
        press_and_wait(h)
        assert h.platform.copy_calls == [WORD]
        assert h.label(h.popup.note_label) == "Sidekick copied your selection."
        assert h.popup.context_text() == "Ths sentense has erors."
        text = h.sent_text()
        assert "<copied_text>\nThs sentense has erors.\n</copied_text>" in text
        assert text.endswith(f"<question>\n{SMART_PROMPT}\n</question>")
        assert h.popup.visible and h.popup.answer_text().endswith("This sentence has errors.")
        assert str(h.popup.paste_back_button.cget("state")) == "normal"
        # the selection Sidekick copied is not reused on the next press
        h.platform.selection = None
        h.press_hotkey(WORD)
        assert h.popup.context_text() == "" and len(api.requests) == 1


def test_one_key_answer_with_gemini(tmp_path, monkeypatch, api, compat):
    with started(tmp_path, monkeypatch, api, send_to="api", provider="gemini",
                 gemini_base_url=compat.base_url) as h:
        h.keyring.set_password(keystore.SERVICE, keystore.GEMINI_ACCOUNT, "AIza-test")
        h.app.on_key_changed()
        assert "Google Gemini (gemini-3.5-flash-lite)" in h.label(h.app.key_label)
        compat.script.append(chunks(["Hello, ", "how are you?"]))
        press_and_wait(h, selection="Bonjour, comment allez-vous ?")
        sent = compat.requests[0]
        assert sent["headers"]["authorization"] == "Bearer AIza-test"
        assert sent["body"]["model"] == "gemini-3.5-flash-lite"
        question = sent["body"]["messages"][1]["content"]
        assert "Bonjour, comment allez-vous ?" in question and SMART_PROMPT in question
        assert h.popup.answer_text().endswith("Hello, how are you?")
        assert h.label(h.popup.status_label) == "Gemini · gemini-3.5-flash-lite"
        assert api.requests == []


def test_one_key_answer_with_ollama_on_this_pc(tmp_path, monkeypatch, api, compat):
    with started(tmp_path, monkeypatch, api, send_to="api", provider="ollama", ollama_url=compat.base_url) as h:
        compat.script.append(chunks(["Local answer."]))
        press_and_wait(h)
        assert "authorization" not in compat.requests[0]["headers"]
        assert compat.requests[0]["body"]["model"] == "gemma4:e4b"
        assert h.popup.answer_text().endswith("Local answer.")
        assert h.label(h.popup.status_label) == "Ollama · gemma4:e4b · free, on this PC"


def test_one_key_answer_with_claude_code(tmp_path, monkeypatch, api):
    log = tmp_path / "claude-calls.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "ok")
    monkeypatch.setattr("sidekick.claude_code_client.config_dir", lambda: tmp_path / "sidekick")
    with started(tmp_path, monkeypatch, api, send_to="api") as h:  # Claude Code is the default service
        assert h.app.settings.provider == "claude_code"
        assert "no API key, no extra bill" in h.label(h.app.key_label)
        press_and_wait(h)
        assert h.popup.answer_text().endswith("Claude Code says hi.")
        assert h.label(h.popup.status_label) == "Claude Code (your Claude plan)"
        prompt = json.loads(log.read_text().splitlines()[0])["stdin"]
        assert "Ths sentense has erors." in prompt and SMART_PROMPT in prompt
        assert api.requests == []


def test_another_service_with_your_own_prices(tmp_path, monkeypatch, api, compat):
    with started(tmp_path, monkeypatch, api, send_to="api", provider="custom", custom_name="Groq",
                 custom_url=compat.base_url, custom_model="llama-4", prices={"custom": [1.0, 2.0]}) as h:
        compat.script.append(chunks(["Done."], usage={"prompt_tokens": 1000, "completion_tokens": 500}))
        press_and_wait(h)
        assert compat.requests[0]["body"]["model"] == "llama-4"
        assert h.label(h.popup.status_label) == "Groq · llama-4 · about 0.2¢ · today 0.2¢"
        assert h.spend.today_total() == pytest.approx(0.002)


def test_the_hotkey_action_can_be_chosen(tmp_path, monkeypatch, api, compat):
    with started(tmp_path, monkeypatch, api, send_to="api", provider="ollama", ollama_url=compat.base_url,
                 hotkey_action="summarize") as h:
        press_and_wait(h, selection="A long report...")
        assert "Summarize this in a few short points." in compat.requests[0]["body"]["messages"][1]["content"]


def test_only_open_the_window(tmp_path, monkeypatch, api, compat):
    with started(tmp_path, monkeypatch, api, send_to="api", provider="ollama", ollama_url=compat.base_url,
                 hotkey_action="open") as h:
        press_and_wait(h, selection="Some text")
        assert h.popup.context_text() == "Some text"  # copied for you, but not sent
        assert compat.requests == []


def test_nothing_selected_just_opens_the_window(tmp_path, monkeypatch, api, compat):
    with started(tmp_path, monkeypatch, api, send_to="api", provider="ollama", ollama_url=compat.base_url) as h:
        press_and_wait(h, selection=None)
        assert h.platform.copy_calls == [WORD]
        assert h.label(h.popup.note_label) == TIP
        assert compat.requests == []


def test_private_windows_are_never_copied(tmp_path, monkeypatch, api, compat):
    with started(tmp_path, monkeypatch, api, send_to="api", provider="ollama", ollama_url=compat.base_url) as h:
        press_and_wait(h, window=BITWARDEN, selection="hunter2")
        assert h.platform.copy_calls == []  # Sidekick did not press any keys there
        assert compat.requests == []


def test_a_fresh_snip_is_asked_about_right_away(tmp_path, monkeypatch, api, compat):
    with started(tmp_path, monkeypatch, api, send_to="api", provider="ollama", ollama_url=compat.base_url) as h:
        h.clear_clipboard()
        h.platform.media = Image.new("RGB", (40, 30), "white")
        press_and_wait(h, selection=None)
        parts = compat.requests[0]["body"]["messages"][1]["content"]
        assert parts[0]["type"] == "image_url" and parts[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_one_key_with_the_claude_app_opens_it_straight_away(tmp_path, monkeypatch, api):
    with started(tmp_path, monkeypatch, api, send_to="claude_app") as h:  # the Claude app, one-key mode on
        press_and_wait(h, selection="=VLOOKUP(A2,B:C,2)")
        (how, url), = h.platform.opened
        question = q_of(url)
        assert '"""\n=VLOOKUP(A2,B:C,2)\n"""' in question and question.endswith(SMART_PROMPT)
        assert not h.popup.visible


def test_paste_back_into_your_app(tmp_path, monkeypatch, api, compat):
    with started(tmp_path, monkeypatch, api, send_to="api", provider="ollama", ollama_url=compat.base_url,
                 hotkey_action="improve") as h:
        compat.script.append(chunks(["This sentence has errors."]))
        press_and_wait(h)
        h.popup.paste_back_button.invoke()
        h.pump(0.2)
        assert h.root.clipboard_get() == "This sentence has errors."
        assert h.platform.pasted == [WORD]
        assert not h.popup.visible and h.app.toast is None

        compat.script.append(chunks(["Again."]))
        h.platform.paste_ok = False  # e.g. the app was closed meanwhile
        press_and_wait(h)
        h.popup.paste_back_button.invoke()
        h.pump(0.2)
        assert "Click where you want it, then press Ctrl+V" in h.app.toast_text


def test_gemini_without_a_key_opens_settings(tmp_path, monkeypatch, api, compat):
    with started(tmp_path, monkeypatch, api, send_to="api", provider="gemini",
                 gemini_base_url=compat.base_url) as h:
        press_and_wait(h)
        dialog = h.app.settings_dialog
        assert dialog is not None and dialog.alive
        assert h.label(dialog.key_label) == "Gemini API key:"
        assert compat.requests == []


def choose_service(dialog, provider):
    dialog.provider_box.current(dialog._provider_ids.index(provider))
    dialog.provider_box.event_generate("<<ComboboxSelected>>")


def test_settings_ai_service_tab(tmp_path, monkeypatch, api):
    with started(tmp_path, monkeypatch, api) as h:
        h.app.open_settings()
        h.pump()
        d = h.app.settings_dialog
        d.send_to_box.current(2)  # answer inside Sidekick
        d.action_box.current(list(d._action_ids).index("fix"))
        choose_service(d, "gemini")
        h.pump()
        assert h.label(d.key_label) == "Gemini API key:"
        assert "No key saved" in h.label(d.key_status)
        d.key_var.set("AIza-123")
        d.on_save_key()
        assert h.keyring.get_password(keystore.SERVICE, keystore.GEMINI_ACCOUNT) == "AIza-123"
        assert h.keyring.get_password(keystore.SERVICE, keystore.ACCOUNT) is None
        d.gemini_model_var.set("gemini-3.8-flash")

        choose_service(d, "custom")
        h.pump()
        d.custom_name_var.set("DeepSeek")
        d.custom_url_var.set("https://api.example.com/v1/")
        d.custom_model_var.set("chat-model")
        d.price_in_var.set("0.27")
        d.price_out_var.set("1.10")
        d.on_save()

        saved = load_settings(h.settings_path)
        assert (saved.send_to, saved.provider, saved.hotkey_action) == ("api", "custom", "fix")
        assert (saved.custom_name, saved.custom_url, saved.custom_model) == (
            "DeepSeek", "https://api.example.com/v1", "chat-model")
        assert saved.gemini_model == "gemini-3.8-flash"
        assert saved.prices == {"custom": [0.27, 1.1]}
        assert "DeepSeek (chat-model)" in h.label(h.app.key_label)


def test_settings_check_what_you_type(tmp_path, monkeypatch, api):
    with started(tmp_path, monkeypatch, api) as h:
        h.app.open_settings()
        d = h.app.settings_dialog
        choose_service(d, "custom")
        h.pump()
        d.on_save()
        assert h.dialogs.titles("error") == ["Other service"]  # address and model are needed
        d.custom_url_var.set("api.example.com")
        d.custom_model_var.set("m")
        d.on_save()
        assert h.dialogs.titles("error")[-1] == "Address"
        d.custom_url_var.set("https://api.example.com/v1")
        d.price_in_var.set("cheap")
        d.on_save()
        assert h.dialogs.titles("error")[-1] == "Prices"
        d.price_in_var.set("")
        choose_service(d, "claude")
        h.pump()
        d.model_var.set("gpt-5")
        d.on_save()
        assert h.dialogs.titles("error")[-1] == "Claude model"
        d.model_var.set("claude-haiku-5-5")
        d.on_save()
        assert not d.alive and load_settings(h.settings_path).model == "claude-haiku-5-5"


def test_claude_cli_mode_is_the_default(tmp_path, monkeypatch, api):
    monkeypatch.setattr("sidekick.app.find_claude", lambda configured="": None)
    with started(tmp_path, monkeypatch, api) as h:  # nothing chosen: all defaults
        s = h.app.settings
        assert (s.send_to, s.provider, s.instant) == ("api", "claude_code", True)
        text = h.label(h.app.key_label)
        assert "from Claude Code on this PC, with your Claude plan" in text
        assert "Claude Code was not found on this PC yet" in text
        assert "Sidekick copies it and asks" in h.label(h.app.howto_label)


def test_daily_limit_does_not_block_free_services(tmp_path, monkeypatch, api, compat):
    with started(tmp_path, monkeypatch, api, send_to="api", provider="ollama", ollama_url=compat.base_url) as h:
        h.spend.add(5.0)  # e.g. spent earlier today with the Claude API
        compat.script.append(chunks(["Free answer."]))
        press_and_wait(h)
        assert h.dialogs.titles("info") == []
        assert h.popup.answer_text().endswith("Free answer.")


def test_a_snip_is_not_sent_to_claude_code(tmp_path, monkeypatch, api):
    log = tmp_path / "claude-calls.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setattr("sidekick.claude_code_client.config_dir", lambda: tmp_path / "sidekick")
    monkeypatch.setattr("sidekick.app.find_claude", lambda configured="": "claude")
    with started(tmp_path, monkeypatch, api) as h:  # the defaults: Claude Code, one-key mode
        assert "Win+Shift+S" not in h.label(h.app.howto_label)
        h.clear_clipboard()
        h.platform.media = Image.new("RGB", (40, 30), "white")
        press_and_wait(h, selection=None)
        assert h.label(h.popup.note_label).startswith("This picture was not sent. Claude Code")
        assert h.popup.answer_text() == "" and not log.exists()


def test_follow_up_after_changing_the_ai_service(tmp_path, monkeypatch, api, compat):
    with started(tmp_path, monkeypatch, api, send_to="api", provider="ollama", ollama_url=compat.base_url) as h:
        compat.script.append(chunks(["First answer."]))
        press_and_wait(h)
        h.app.settings.provider = "claude"  # changed in Settings while the answer is shown
        h.app.on_settings_changed(hotkey_changed=False)
        h.set_key()
        h.ask("And why?")
        assert "Click New question" in h.label(h.popup.status_label)
        assert api.requests == [] and len(compat.requests) == 1


def test_the_window_names_the_service_that_gets_the_text(tmp_path, monkeypatch, api, compat):
    with started(tmp_path, monkeypatch, api, send_to="api", provider="gemini",
                 gemini_base_url=compat.base_url) as h:
        h.press_hotkey(WORD)
        assert h.label(h.popup.send_frame) == "What will be sent to Google Gemini (you can edit or delete it)"
