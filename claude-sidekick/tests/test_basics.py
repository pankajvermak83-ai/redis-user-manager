"""Tests for the small building blocks: settings, hotkeys, privacy, costs,
attachments, the message that is sent, and the clipboard rules."""

import datetime
import io
import json
import types

import pytest

from sidekick.attachments import Attachment, AttachmentError, attachment_from_path, image_attachment
from sidekick.capture import TIP, ClipboardWatch, capture_context, read_clipboard
from sidekick.config import DEFAULT_PRIVATE_WORDS, Settings, load_settings, save_settings
from sidekick.costs import DailySpend, estimate_cost, format_money, input_cost
from sidekick.hotkeys import parse_hotkey
from sidekick.platform_base import Platform, WindowInfo
from sidekick.privacy import find_secrets, is_private_window
from sidekick.prompts import build_first_message

Image = pytest.importorskip("PIL.Image")


# ------------------------------------------------------------------ settings


def test_settings_survive_a_save_and_load(tmp_path):
    path = tmp_path / "config.json"
    s = Settings(model="claude-sonnet-5-5", effort="low", hotkey="ctrl+alt+a", daily_limit_usd=3.5)
    save_settings(s, path)
    loaded = load_settings(path)
    assert loaded == s
    assert not (tmp_path / "config.json.tmp").exists()  # the temporary file was renamed


def test_questions_go_to_the_claude_app_by_default():
    assert Settings().send_to == "claude_app"
    assert Settings.from_dict({"send_to": "api"}).send_to == "api"
    assert Settings.from_dict({"send_to": "chrome"}).send_to == "chrome"
    assert Settings.from_dict({"send_to": "fax"}).send_to == "claude_app"


def test_damaged_or_missing_settings_fall_back_to_defaults(tmp_path):
    assert load_settings(tmp_path / "nope.json") == Settings()
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    assert load_settings(bad) == Settings()


def test_bad_values_are_ignored_or_clamped():
    s = Settings.from_dict({
        "model": "gpt-9",  # unknown model -> default
        "effort": "extreme",  # unknown effort -> default
        "max_output_tokens": 10,  # too small -> raised to the minimum
        "daily_limit_usd": -5,  # negative -> 0
        "max_image_edge": 99999,  # too big -> the API's maximum
        "send_window_title": "yes",  # not a true/false value -> default
        "private_words": ["  Bank ", "", 42],
        "quick_actions": [{"label": "Hi", "prompt": "Say hi"}, {"label": ""}, "junk"],
    })
    assert s.model == "claude-opus-5-5"
    assert s.effort == "medium"
    assert s.max_output_tokens == 1000
    assert s.daily_limit_usd == 0.0
    assert s.max_image_edge == 2576
    assert s.send_window_title is True
    assert s.private_words == ["bank"]
    assert s.quick_actions == [{"label": "Hi", "prompt": "Say hi"}]
    assert Settings.from_dict(None) == Settings()
    assert Settings.from_dict({"daily_limit_usd": True}).daily_limit_usd == 2.0


# ------------------------------------------------------------------- hotkeys


def test_hotkey_parsing():
    hk = parse_hotkey(" Control + Shift + Spacebar ")
    assert str(hk) == "ctrl+shift+space"
    assert hk.pretty() == "Ctrl+Shift+Space"
    assert str(parse_hotkey("shift+ctrl+f9")) == "ctrl+shift+f9"
    assert parse_hotkey("win+alt+k").pretty() == "Alt+Win+K"


@pytest.mark.parametrize("text, reason", [
    ("", "empty"),
    ("ctrl+", "Write the hotkey"),
    ("ctrl+shift", "exactly one normal key"),
    ("ctrl+a+b", "exactly one normal key"),
    ("shift+a", "Add Ctrl, Alt or Win"),
    ("ctrl+f25", "cannot be used"),
    ("ctrl+é", "cannot be used"),
])
def test_unusable_hotkeys_are_explained(text, reason):
    with pytest.raises(ValueError) as caught:
        parse_hotkey(text)
    assert reason in str(caught.value)


# ------------------------------------------------------------------- privacy


def test_private_windows_are_recognised():
    words = DEFAULT_PRIVATE_WORDS
    assert is_private_window(WindowInfo("Vault - Bitwarden", "bitwarden.exe"), words)
    assert is_private_window(WindowInfo("New InPrivate tab - Microsoft Edge", "msedge.exe"), words)
    assert is_private_window(WindowInfo("Database.kdbx - KeePass", "keepass.exe"), words)
    assert is_private_window(WindowInfo("Windows Security", "credentialuibroker.exe"), words)
    assert is_private_window(WindowInfo("Passwords.txt - Notepad", "notepad.exe"), words)
    assert is_private_window(WindowInfo("Online Banking - Google Chrome", "chrome.exe"), words)
    assert not is_private_window(WindowInfo("Budget.xlsx - Excel", "excel.exe"), words)
    assert not is_private_window(None, words)


def test_private_words_must_start_a_word():
    words = DEFAULT_PRIVATE_WORDS
    # "sign in", "log in" and "keeper" hide inside these titles, but only mid-word
    assert not is_private_window(WindowInfo("Design input.xlsx - Excel", "excel.exe"), words)
    assert not is_private_window(WindowInfo("Catalog index.docx - Word", "winword.exe"), words)
    assert not is_private_window(WindowInfo("Bookkeeper notes - Notepad", "notepad.exe"), words)


def test_secrets_are_spotted():
    assert find_secrets("my password: hunter2") == ["a password"]
    assert find_secrets("key sk-ant-api03-abcdefghijklmnopqrstuvwxyz") == ["an API key"]
    assert find_secrets("-----BEGIN RSA PRIVATE KEY-----\nabc") == ["a private key"]
    assert find_secrets("card 4111 1111 1111 1111 exp 12/29") == ["a card number"]
    assert "an access token" in find_secrets("token ghp_" + "a" * 36)


def test_ordinary_text_is_not_flagged():
    assert find_secrets("Please summarise the meeting notes from Tuesday.") == []
    assert find_secrets("Order 1234567890123 shipped") == []  # fails the card checksum
    assert find_secrets("0000 0000 0000 0000") == []  # all the same digit
    assert find_secrets("Reset your password from the settings page.") == []


# --------------------------------------------------------------------- costs


def usage(**kw):
    base = dict(input_tokens=0, output_tokens=0, cache_creation_input_tokens=0, cache_read_input_tokens=0, iterations=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_cost_estimates():
    assert estimate_cost("claude-opus-5-5", usage(input_tokens=3000, output_tokens=500)) == pytest.approx(0.022)
    assert estimate_cost("claude-sonnet-5-5", usage(input_tokens=3000, output_tokens=500)) == pytest.approx(0.011)
    assert estimate_cost("claude-haiku-5-5", usage(input_tokens=3000, output_tokens=500)) == pytest.approx(0.00055)
    # cached reads are cheap; cache writes cost a little extra
    cached = usage(input_tokens=100, cache_read_input_tokens=10000, cache_creation_input_tokens=1000, output_tokens=100)
    expected = (100 * 4 + 10000 * 0.20 + 1000 * 4 * 1.25 + 100 * 20) / 1_000_000
    assert estimate_cost("claude-opus-5-5", cached) == pytest.approx(expected)
    # Haiku's long-prompt price
    assert estimate_cost("claude-haiku-5-5", usage(input_tokens=200_000)) == pytest.approx(0.10)
    assert estimate_cost("some-new-model", usage(input_tokens=10)) is None
    assert estimate_cost("claude-opus-5-5", None) is None
    assert input_cost("claude-opus-5-5", 250_000) == pytest.approx(1.0)


def test_money_is_shown_simply():
    assert format_money(None) == "cost unknown"
    assert format_money(0.0001) == "under 0.1¢"
    assert format_money(0.022) == "2.2¢"
    assert format_money(0.45) == "45¢"
    assert format_money(2.5) == "$2.50"


def test_daily_spend_resets_each_day(tmp_path, monkeypatch):
    path = tmp_path / "usage.json"
    spend = DailySpend(path)
    assert spend.today_total() == 0.0
    spend.add(0.25)
    assert spend.add(0.5) == pytest.approx(0.75)
    data = json.loads(path.read_text())
    assert data["requests"] == 2 and data["usd"] == pytest.approx(0.75)
    assert set(data) == {"date", "usd", "requests"}  # no questions or answers are stored

    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    monkeypatch.setattr(DailySpend, "_today", staticmethod(lambda: tomorrow))
    assert spend.today_total() == 0.0
    spend.add(0.1)
    assert json.loads(path.read_text())["requests"] == 1


# --------------------------------------------------------------- attachments


def test_big_picture_is_shrunk_and_sent_as_png():
    att = image_attachment(Image.new("RGB", (4000, 1000), "white"), "", 1920)
    assert att.kind == "image" and att.media_type == "image/png"
    assert att.detail == "1920 x 480"
    with Image.open(io.BytesIO(att.data)) as img:
        assert img.size == (1920, 480)
    block = att.content_block()
    assert block["type"] == "image" and block["source"]["media_type"] == "image/png"


def test_small_picture_is_not_enlarged():
    assert image_attachment(Image.new("RGB", (300, 200)), "", 1920).detail == "300 x 200"


def test_files_on_disk(tmp_path):
    notes = tmp_path / "notes.txt"
    notes.write_bytes("\ufeffMeeting at 10".encode("utf-8"))
    att = attachment_from_path(str(notes), 1920)
    assert att.kind == "text" and att.text() == "Meeting at 10"
    assert att.path == str(notes)
    assert att.content_block() is None

    old = tmp_path / "old.txt"
    old.write_bytes("caf\xe9".encode("cp1252"))
    assert attachment_from_path(str(old), 1920).text() == "café"

    wide = tmp_path / "wide.txt"
    wide.write_bytes("hello".encode("utf-16"))
    assert attachment_from_path(str(wide), 1920).text() == "hello"

    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%fake but fine\n")
    att = attachment_from_path(str(pdf), 1920)
    assert att.kind == "pdf" and att.content_block()["type"] == "document"

    bmp = tmp_path / "shot.bmp"
    Image.new("RGB", (50, 40)).save(bmp)
    att = attachment_from_path(str(bmp), 1920)
    assert att.kind == "image" and att.media_type == "image/png"


@pytest.mark.parametrize("name, data, message", [
    ("budget.xlsx", b"PK\x03\x04", "cannot open Word, Excel or PowerPoint"),
    ("tool.exe", b"MZ\x00\x00binary", "cannot read"),
    ("empty.txt", b"", "is empty"),
    ("fake.pdf", b"not really a pdf", "does not look like a real PDF"),
    ("broken.png", b"not an image", "could not be read as a picture"),
])
def test_unusable_files_are_explained(tmp_path, name, data, message):
    path = tmp_path / name
    path.write_bytes(data)
    with pytest.raises(AttachmentError) as caught:
        attachment_from_path(str(path), 1920)
    assert message in str(caught.value)


def test_folders_and_huge_text_files_are_refused(tmp_path):
    with pytest.raises(AttachmentError):
        attachment_from_path(str(tmp_path), 1920)
    big = tmp_path / "big.log"
    big.write_bytes(b"x" * 500_000)
    with pytest.raises(AttachmentError) as caught:
        attachment_from_path(str(big), 1920)
    assert "too big" in str(caught.value)


# ----------------------------------------------------------- what is sent


def test_first_message_layout():
    window = WindowInfo("Budget.xlsx - Excel", "excel.exe", 7)
    picture = Attachment("image", "", "image/png", b"png-bytes", "10 x 10")
    blocks = build_first_message("Why #REF?", "=SUM(A1:A3)", window, picture)
    assert blocks[0]["type"] == "image"  # pictures go before the words
    text = blocks[1]["text"]
    assert "<active_window>\napp: Excel\ntitle: Budget.xlsx - Excel\n</active_window>" in text
    assert "<copied_text>\n=SUM(A1:A3)\n</copied_text>" in text
    assert text.endswith("<question>\nWhy #REF?\n</question>")


def test_first_message_without_extras():
    blocks = build_first_message("Hi", "", None, None)
    assert blocks == [{"type": "text", "text": "<question>\nHi\n</question>"}]


def test_text_file_goes_inside_the_question():
    note = Attachment("text", "notes.txt", "text/plain", b"line one")
    blocks = build_first_message("Summarize", "", None, note)
    assert len(blocks) == 1
    assert '<file name="notes.txt">\nline one\n</file>' in blocks[0]["text"]


# --------------------------------------------------------- clipboard rules


class FakePlatform(Platform):
    def __init__(self):
        self.seq = 1
        self.private = False

    def clipboard_sequence(self):
        return self.seq

    def clipboard_marked_private(self):
        return self.private


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_watch():
    platform, clock = FakePlatform(), Clock()
    return platform, clock, ClipboardWatch(platform, clock)


def capture(watch, platform, text="", media=None, window=None, settings=None):
    return capture_context(window, watch, platform, lambda: text, lambda: media, settings or Settings())


def test_only_recent_copies_are_used():
    platform, clock, watch = make_watch()
    # something was on the clipboard before Sidekick started: ignored
    assert capture(watch, platform, "old stuff").note == TIP

    platform.seq += 1  # the user copies something
    watch.poll()
    result = capture(watch, platform, "fresh text")
    assert result.text == "fresh text" and "Nothing is sent" in result.note

    clock.now += 121  # two minutes later it is no longer "just copied"
    assert capture(watch, platform, "fresh text").text == ""


def test_copy_noticed_even_without_polling():
    platform, clock, watch = make_watch()
    platform.seq += 1
    assert capture(watch, platform, "abc").text == "abc"


def test_private_marker_and_private_window():
    platform, clock, watch = make_watch()
    platform.seq += 1
    platform.private = True
    result = capture(watch, platform, "hunter2")
    assert result.text == "" and "marked private" in result.note

    platform.private = False
    window = WindowInfo("Vault - Bitwarden", "bitwarden.exe")
    result = capture(watch, platform, "hunter2", window=window)
    assert result.private and result.text == "" and "private window" in result.note


def test_sidekicks_own_copy_is_not_treated_as_new():
    platform, clock, watch = make_watch()
    platform.seq += 1
    watch.note_own_copy("the answer")
    # Windows can bump the clipboard counter again later (for example when
    # another app pastes Sidekick's answer), so the text itself is checked too.
    platform.seq += 1
    assert capture(watch, platform, "the answer").note == TIP


def test_long_copies_are_trimmed_with_a_note():
    settings = Settings(max_text_chars=1000)
    text, att, note = read_clipboard(lambda: "x" * 5000, lambda: None, settings)
    assert len(text) == 1000 and att is None
    assert "5,000" in note and "1,000" in note


def test_copied_picture_and_copied_files(tmp_path):
    settings = Settings()
    text, att, note = read_clipboard(lambda: "", lambda: Image.new("RGB", (10, 10)), settings)
    assert text == "" and att.kind == "image" and "picture" in note

    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("first", encoding="utf-8")
    b.write_text("second", encoding="utf-8")
    text, att, note = read_clipboard(lambda: "", lambda: [str(a), str(b)], settings)
    assert att.name == "a.txt" and "1 other copied file" in note

    text, att, note = read_clipboard(lambda: "", lambda: None, settings)
    assert att is None and "nothing Sidekick can use" in note


def test_snipped_picture_can_be_saved_for_dragging(tmp_path, monkeypatch):
    from sidekick.attachments import save_to_temp_file

    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    snip = image_attachment(Image.new("RGB", (20, 10)), "", 1920)
    path = save_to_temp_file(snip)
    assert path == str(tmp_path / "Sidekick" / "Sidekick picture.png")
    assert snip.path == path and snip.name == "Sidekick picture.png"
    with Image.open(path) as img:
        assert img.size == (20, 10)


# ------------------------------------------------ AI services, one key, prices


def test_ai_service_settings():
    s = Settings()
    assert (s.instant, s.hotkey_action, s.provider) == (True, "smart", "claude_code")
    loaded = Settings.from_dict({
        "instant": False, "hotkey_action": "fix", "provider": "gemini",
        "gemini_model": " gemini-9-flash ", "ollama_url": "http://192.168.1.5:11434/v1/",
        "custom_url": "ftp://nope", "model": "claude-future-9",
        "prices": {"gemini": [0.3, 2.5], "custom": ["a", 1], "nobody": [1, 1], "claude": [1, 2, 3]},
    })
    assert (loaded.instant, loaded.hotkey_action, loaded.provider) == (False, "fix", "gemini")
    assert loaded.gemini_model == "gemini-9-flash"  # new model names can be typed in
    assert loaded.ollama_url == "http://192.168.1.5:11434/v1"
    assert loaded.custom_url == ""  # not a web address: ignored
    assert loaded.model == "claude-future-9"
    assert loaded.prices == {"gemini": [0.3, 2.5]}  # bad price entries are dropped
    assert Settings.from_dict({"provider": "skynet", "hotkey_action": "dance", "model": "gpt-5"}) == Settings()


def test_your_prices_replace_the_built_in_ones():
    use = usage(input_tokens=1000, output_tokens=500, cache_read_input_tokens=1000)
    assert estimate_cost("claude-opus-5-5", use, [1.0, 2.0]) == pytest.approx((2000 * 1 + 500 * 2) / 1_000_000)
    assert estimate_cost("claude-future-9", use) is None  # unknown model, no prices given
    assert estimate_cost("claude-future-9", use, [1.0, 2.0]) is not None


def test_each_service_has_its_own_key(monkeypatch):
    from sidekick import keystore, services

    store = {}
    fake = type("FakeKeyring", (), {
        "get_password": staticmethod(lambda svc, acct: store.get(acct)),
        "set_password": staticmethod(lambda svc, acct, value: store.__setitem__(acct, value)),
        "delete_password": staticmethod(lambda svc, acct: store.pop(acct, None)),
    })
    monkeypatch.setattr(keystore, "_keyring", lambda: fake)
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    keystore.save_api_key("AIza-1", keystore.GEMINI_ACCOUNT)
    assert services.load_key("gemini") == "AIza-1" and services.load_key("claude") is None
    assert services.has_key(Settings(provider="gemini")) and not services.has_key(Settings(provider="claude"))
    assert services.has_key(Settings(provider="claude_code")) and services.has_key(Settings(provider="ollama"))
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-env")
    keystore.delete_api_key(keystore.GEMINI_ACCOUNT)
    assert services.load_key("gemini") == "AIza-env"
