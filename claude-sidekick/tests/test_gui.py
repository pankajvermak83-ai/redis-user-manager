"""End-to-end tests of the real Sidekick windows.

Each test opens the actual main window and Ask popup (on a virtual screen
when run with xvfb-run), clicks through them like a person would, and
checks what was sent to a fake Claude server running on this computer.
Windows itself is replaced by FakePlatform, and the system key store by
FakeKeyring, so no real hotkey, clipboard watcher, API key or internet is used.
"""

import gc
import os
import time

import pytest

tk = pytest.importorskip("tkinter")
Image = pytest.importorskip("PIL.Image")

from fake_api import FakeAnthropic, api_error, sse_events  # noqa: E402
from sidekick import keystore  # noqa: E402
from sidekick.app import SidekickApp  # noqa: E402
from sidekick.capture import TIP  # noqa: E402
from sidekick.claude_client import ClaudeClient  # noqa: E402
from sidekick.config import Settings, load_settings  # noqa: E402
from sidekick.costs import DailySpend  # noqa: E402
from sidekick.platform_base import Platform, WindowInfo  # noqa: E402
from sidekick.popup import Dialogs  # noqa: E402

EXCEL = WindowInfo("Budget.xlsx - Excel", "excel.exe", 4321)
BITWARDEN = WindowInfo("My vault - Bitwarden", "bitwarden.exe", 555)


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
        self.app = SidekickApp(
            self.root, self.platform, settings or Settings(), self.spend,
            settings_path=self.settings_path, dialogs=self.dialogs,
            client_factory=lambda s, key: ClaudeClient(s, api_key=key, base_url=api.base_url, max_retries=0),
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
        self.app.hotkey_events.put(window)
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
    assert "Nothing is sent until you click Ask" in h.label(h.popup.note_label)
    assert h.api.requests == []  # nothing is sent before Ask

    h.api.script.append(sse_events(["Add the missing", " bracket:\n=SUM(A1:A3)"]))
    h.ask("Why is this formula wrong?")

    assert h.popup.answer_text() == "Add the missing bracket:\n=SUM(A1:A3)"
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
    assert "--- You asked: How do I answer? ---" in shown
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
    harness = Harness(tmp_path, monkeypatch, api, settings=Settings(send_window_title=False))
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
    assert "No key yet" in h.label(dialog.key_status)

    dialog.key_var.set("sk-ant-new-key")
    dialog.on_save_key()
    assert h.keyring.get_password(keystore.SERVICE, keystore.ACCOUNT) == "sk-ant-new-key"
    assert dialog.key_var.get() == ""  # the box is cleared after saving
    assert h.label(h.app.key_label) == "API key: saved"


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
    assert (saved.model, saved.effort, saved.hotkey, saved.daily_limit_usd, saved.send_window_title) == (
        "claude-sonnet-5-5", "low", "ctrl+alt+k", 3.0, False)
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
