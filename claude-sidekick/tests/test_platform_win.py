"""Tests for the Windows layer.

These run on any computer by swapping the real Windows libraries for small
imitations ("fakes"). They check Sidekick's own logic: starting and stopping
the hotkey listener, what happens when the hotkey is taken, and so on. They
cannot prove that real Windows behaves as the fakes do."""

import ctypes
import queue
import threading
import time

from sidekick.hotkeys import parse_hotkey
from sidekick.platform_base import WindowInfo
from sidekick.platform_win import (
    ERROR_ALREADY_EXISTS, ERROR_HOTKEY_ALREADY_REGISTERED, HOTKEY_ID, INPUT, KEYEVENTF_EXTENDEDKEY,
    KEYEVENTF_KEYUP, MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT, SIDEKICK_TAG, VK_C, VK_CONTROL,
    VK_INSERT, VK_SHIFT, VK_V, WM_HOTKEY, WM_QUIT, Win32Api, WindowsPlatform, modifier_flags,
    virtual_key,
)


class Fn:
    """A stand-in for a Windows function (accepts .argtypes / .restype)."""

    def __init__(self, func):
        self._func = func

    def __call__(self, *args):
        return self._func(*args)


class FakeWindows:
    def __init__(self):
        self.messages = queue.Queue()
        self.registered = []
        self.unregistered = []
        self.hotkey_taken = False
        self.last_error = 0
        self.foreground = (4242, "Budget.xlsx - Excel", 777, r"C:\Program Files\Microsoft Office\EXCEL.EXE")
        self.clipboard_seq = 10
        self.clipboard_formats = set()
        self.closed_handles = []
        self.mutex_exists = False
        self.dpi_calls = []
        # keyboard and windows, for one-key mode
        self.held = set()  # keys you are still holding down
        self.sent = []  # each SendInput call: [(key, flags), ...]
        self.copies_with = {"insert", "c"}  # copy keys the app in front understands
        self.has_selection = True
        self.windows = {4242}  # windows that exist
        self.comes_to_front = True
        self.pasted_into = []

        u, k, s = type("U", (), {})(), type("K", (), {})(), type("S", (), {})()
        u.RegisterHotKey = Fn(self._register)
        u.UnregisterHotKey = Fn(lambda hwnd, hid: self.unregistered.append(hid) or 1)
        u.GetMessageW = Fn(self._get_message)
        u.PeekMessageW = Fn(lambda *a: 0)
        u.PostThreadMessageW = Fn(lambda tid, msg, w, l: self.messages.put((msg, w)) or 1)
        u.GetForegroundWindow = Fn(lambda: self.foreground[0] if self.foreground else None)
        u.GetWindowTextLengthW = Fn(lambda hwnd: len(self.foreground[1]))
        u.GetWindowTextW = Fn(self._window_text)
        u.GetWindowThreadProcessId = Fn(self._pid)
        u.GetClipboardSequenceNumber = Fn(lambda: self.clipboard_seq)
        u.RegisterClipboardFormatW = Fn(lambda name: 50000 + sum(map(ord, name)) % 1000)
        u.IsClipboardFormatAvailable = Fn(lambda fmt: 1 if fmt in self.clipboard_formats else 0)
        u.SendInput = Fn(self._send_input)
        u.GetAsyncKeyState = Fn(lambda vk: 0x8000 if vk in self.held else 0)
        u.MapVirtualKeyW = Fn(lambda vk, kind: 0x100 + vk)
        u.SetForegroundWindow = Fn(self._set_foreground)
        u.IsWindow = Fn(lambda hwnd: 1 if hwnd in self.windows else 0)
        k.GetCurrentThreadId = Fn(lambda: threading.get_ident() % 100000)
        k.OpenProcess = Fn(lambda access, inherit, pid: 99)
        k.QueryFullProcessImageNameW = Fn(self._image_name)
        k.CloseHandle = Fn(lambda h: self.closed_handles.append(h) or 1)
        k.CreateMutexW = Fn(self._mutex)
        s.SetProcessDpiAwareness = Fn(lambda v: self.dpi_calls.append(v) or 0)
        self.api = Win32Api(u, k, s, lambda: self.last_error)

    def format_id(self, name):
        return self.api.user32.RegisterClipboardFormatW(name)

    def _register(self, hwnd, hid, flags, vk):
        if self.hotkey_taken:
            self.last_error = ERROR_HOTKEY_ALREADY_REGISTERED
            return 0
        self.registered.append((hid, flags, vk))
        return 1

    def _get_message(self, msg_ref, hwnd, lo, hi):
        message, wparam = self.messages.get(timeout=5)
        if message == WM_QUIT:
            return 0
        msg_ref._obj.message = message
        msg_ref._obj.wParam = wparam
        return 1

    def _window_text(self, hwnd, buf, size):
        buf.value = self.foreground[1]
        return len(buf.value)

    def _pid(self, hwnd, pid_ref):
        pid_ref._obj.value = self.foreground[2]
        return 1

    def _image_name(self, handle, flags, buf, size_ref):
        buf.value = self.foreground[3]
        return 1

    def _mutex(self, attrs, owner, name):
        self.last_error = ERROR_ALREADY_EXISTS if self.mutex_exists else 0
        return 55

    def press_hotkey(self):
        self.messages.put((WM_HOTKEY, HOTKEY_ID))

    def _send_input(self, count, events, size):
        assert size == ctypes.sizeof(INPUT)
        keys = []
        for i in range(count):
            ki = events[i].u.ki
            assert events[i].type == 1 and ki.dwExtraInfo == SIDEKICK_TAG and ki.wScan == 0x100 + ki.wVk
            keys.append((ki.wVk, ki.dwFlags))
        self.sent.append(keys)
        downs = [vk for vk, flags in keys if not flags & KEYEVENTF_KEYUP]
        if (downs == [VK_CONTROL, VK_INSERT] and "insert" in self.copies_with) or (
                downs == [VK_CONTROL, VK_C] and "c" in self.copies_with):
            if self.has_selection:
                self.clipboard_seq += 1  # the app copied the selection
        if downs in ([VK_CONTROL, VK_V], [VK_SHIFT, VK_INSERT]):
            self.pasted_into.append(self.foreground[0])
        return count

    def _set_foreground(self, hwnd):
        if self.comes_to_front and hwnd in self.windows:
            self.foreground = (hwnd,) + tuple(self.foreground[1:])
        return 1


def test_key_numbers():
    assert virtual_key("space") == 0x20
    assert virtual_key("a") == 0x41
    assert virtual_key("7") == 0x37
    assert virtual_key("f1") == 0x70 and virtual_key("f12") == 0x7B
    assert modifier_flags(parse_hotkey("ctrl+shift+space")) == MOD_CONTROL | MOD_SHIFT
    assert modifier_flags(parse_hotkey("ctrl+alt+a")) == MOD_CONTROL | MOD_ALT


def test_hotkey_press_reports_the_window_you_were_in():
    fake = FakeWindows()
    platform = WindowsPlatform(fake.api)
    seen = queue.Queue()

    ok, problem = platform.start_hotkey(parse_hotkey("ctrl+shift+space"), seen.put)
    assert ok and problem == ""
    assert fake.registered == [(HOTKEY_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, 0x20)]

    fake.press_hotkey()
    info = seen.get(timeout=3)
    assert info == WindowInfo(title="Budget.xlsx - Excel", exe="excel.exe", pid=777)
    assert fake.closed_handles == [99]  # the process handle was released

    platform.stop_hotkey()
    assert fake.unregistered == [HOTKEY_ID]  # the hotkey is given back to Windows


def test_other_messages_are_ignored():
    fake = FakeWindows()
    platform = WindowsPlatform(fake.api)
    seen = queue.Queue()
    platform.start_hotkey(parse_hotkey("ctrl+shift+space"), seen.put)
    fake.messages.put((WM_HOTKEY, 1))  # somebody else's hotkey id
    fake.messages.put((0x0113, 0))  # an unrelated message
    fake.press_hotkey()
    assert seen.get(timeout=3).exe == "excel.exe"
    assert seen.empty()
    platform.stop_hotkey()


def test_hotkey_already_used_by_another_app():
    fake = FakeWindows()
    fake.hotkey_taken = True
    ok, problem = WindowsPlatform(fake.api).start_hotkey(parse_hotkey("ctrl+shift+space"), lambda info: None)
    assert not ok and problem == "in_use"
    assert fake.unregistered == []


def test_changing_the_hotkey_releases_the_old_one():
    fake = FakeWindows()
    platform = WindowsPlatform(fake.api)
    platform.start_hotkey(parse_hotkey("ctrl+shift+space"), lambda info: None)
    platform.start_hotkey(parse_hotkey("ctrl+alt+a"), lambda info: None)
    assert fake.unregistered == [HOTKEY_ID]
    assert fake.registered[-1] == (HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, 0x41)
    platform.stop_hotkey()


def test_a_crash_in_the_handler_does_not_stop_the_listener():
    fake = FakeWindows()
    platform = WindowsPlatform(fake.api)
    seen = queue.Queue()
    calls = []

    def handler(info):
        calls.append(info)
        if len(calls) == 1:
            raise RuntimeError("boom")
        seen.put(info)

    platform.start_hotkey(parse_hotkey("ctrl+shift+space"), handler)
    fake.press_hotkey()
    fake.press_hotkey()
    assert seen.get(timeout=3).pid == 777
    platform.stop_hotkey()


def test_no_window_in_front():
    fake = FakeWindows()
    fake.foreground = None
    assert WindowsPlatform(fake.api).foreground_window() is None


def test_clipboard_counter_and_private_marker():
    fake = FakeWindows()
    platform = WindowsPlatform(fake.api)
    assert platform.clipboard_sequence() == 10
    assert platform.clipboard_marked_private() is False
    fake.clipboard_formats.add(fake.format_id("ExcludeClipboardContentFromMonitorProcessing"))
    assert platform.clipboard_marked_private() is True


def test_second_copy_of_sidekick_is_detected():
    fake = FakeWindows()
    assert WindowsPlatform(fake.api).acquire_single_instance() is True
    fake.mutex_exists = True
    assert WindowsPlatform(fake.api).acquire_single_instance() is False


def test_prepare_process_sets_sharp_text_mode():
    fake = FakeWindows()
    WindowsPlatform(fake.api).prepare_process()
    assert fake.dpi_calls == [1]


# ------------------------------------------------ Claude app, Chrome, Explorer

from sidekick.platform_win import CHROME_APP_PATH, find_chrome  # noqa: E402


class FakeKey:
    def __init__(self, values):
        self.values = values

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeWinreg:
    """A stand-in for Python's winreg module (the Windows registry)."""

    HKEY_CLASSES_ROOT, HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE = "HKCR", "HKCU", "HKLM"

    def __init__(self, keys):
        self.keys = keys  # {(hive, path): {value name: value}}

    def OpenKey(self, hive, path):
        if (hive, path) not in self.keys:
            raise FileNotFoundError(path)
        return FakeKey(self.keys[(hive, path)])

    def QueryValueEx(self, key, name):
        if name not in key.values:
            raise FileNotFoundError(name)
        return key.values[name], 1


def test_claude_app_is_detected_by_its_link_type():
    api = FakeWindows().api
    installed = FakeWinreg({("HKCR", "claude"): {"": "URL:claude", "URL Protocol": ""}})
    assert WindowsPlatform(api, winreg=installed).claude_app_installed()
    not_a_link_type = FakeWinreg({("HKCR", "claude"): {"": "something else"}})
    assert not WindowsPlatform(api, winreg=not_a_link_type).claude_app_installed()
    assert not WindowsPlatform(api, winreg=FakeWinreg({})).claude_app_installed()


def test_finding_chrome():
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    registered = FakeWinreg({("HKLM", CHROME_APP_PATH): {"": f'"{chrome}"'}})
    assert find_chrome(registered, {}, lambda p: p == chrome) == chrome
    # a registry entry for a Chrome that was deleted is ignored
    assert find_chrome(registered, {}, lambda p: False) is None

    local = r"C:\Users\Pat\AppData\Local\Google\Chrome\Application\chrome.exe"
    environ = {"LOCALAPPDATA": r"C:\Users\Pat\AppData\Local"}
    assert find_chrome(FakeWinreg({}), environ, lambda p: p == local) == local
    assert find_chrome(FakeWinreg({}), {}, lambda p: True) is None


def test_opening_links_chrome_and_file_explorer():
    started, launched = [], []

    def startfile(url):
        if url.startswith("broken:"):
            raise OSError("No application is associated with this link")
        started.append(url)

    chrome = r"C:\Chrome\chrome.exe"
    platform = WindowsPlatform(
        FakeWindows().api,
        winreg=FakeWinreg({("HKCU", CHROME_APP_PATH): {"": chrome}}),
        startfile=startfile, popen=launched.append, isfile=lambda p: p == chrome, environ={},
    )
    assert platform.open_link("claude://claude.ai/new?q=Hi")
    assert started == ["claude://claude.ai/new?q=Hi"]
    assert not platform.open_link("broken://x")

    assert platform.open_in_chrome("https://claude.ai/new")
    assert launched[-1] == [chrome, "https://claude.ai/new"]

    assert platform.reveal_file(r"C:\My Docs\report.pdf")
    assert launched[-1] == 'explorer /select,"C:\\My Docs\\report.pdf"'


def test_no_chrome_installed():
    launched = []
    platform = WindowsPlatform(FakeWindows().api, winreg=FakeWinreg({}), popen=launched.append,
                               isfile=lambda p: False, environ={})
    assert not platform.open_in_chrome("https://claude.ai/new")
    assert launched == []



# ----------------------------------------------------------------- one-key mode

CTRL_INSERT = [(VK_CONTROL, 0), (VK_INSERT, KEYEVENTF_EXTENDEDKEY),
               (VK_INSERT, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP), (VK_CONTROL, KEYEVENTF_KEYUP)]
CTRL_C = [(VK_CONTROL, 0), (VK_C, 0), (VK_C, KEYEVENTF_KEYUP), (VK_CONTROL, KEYEVENTF_KEYUP)]
CTRL_V = [(VK_CONTROL, 0), (VK_V, 0), (VK_V, KEYEVENTF_KEYUP), (VK_CONTROL, KEYEVENTF_KEYUP)]
SHIFT_INSERT = [(VK_SHIFT, 0), (VK_INSERT, KEYEVENTF_EXTENDEDKEY),
                (VK_INSERT, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP), (VK_SHIFT, KEYEVENTF_KEYUP)]
WORD = WindowInfo("Letter.docx - Word", "winword.exe", 77, hwnd=4242)
TERMINAL = WindowInfo("Windows PowerShell", "windowsterminal.exe", 78, hwnd=4242)


def quick_platform(fake):
    platform = WindowsPlatform(fake.api)
    platform.release_timeout = platform.copy_timeout = 0.15
    return platform


def test_foreground_window_includes_its_handle():
    info = WindowsPlatform(FakeWindows().api).foreground_window()
    assert info.hwnd == 4242


def test_copy_uses_ctrl_insert_first():
    fake = FakeWindows()
    assert quick_platform(fake).copy_selection(WORD)
    assert fake.sent == [CTRL_INSERT]


def test_copy_falls_back_to_ctrl_c():
    fake = FakeWindows()
    fake.copies_with = {"c"}  # an app that ignores Ctrl+Insert
    assert quick_platform(fake).copy_selection(WORD)
    assert fake.sent == [CTRL_INSERT, CTRL_C]


def test_terminals_never_get_ctrl_c():
    fake = FakeWindows()
    fake.copies_with = {"c"}
    assert not quick_platform(fake).copy_selection(TERMINAL)
    assert fake.sent == [CTRL_INSERT]  # Ctrl+C could stop a running program


def test_nothing_selected():
    fake = FakeWindows()
    fake.has_selection = False
    assert not quick_platform(fake).copy_selection(WORD)
    assert fake.sent == [CTRL_INSERT, CTRL_C]


def test_waits_until_the_hotkey_is_released():
    fake = FakeWindows()
    platform = quick_platform(fake)
    fake.held = {VK_SHIFT}
    assert not platform.copy_selection(WORD)  # still held after the wait: nothing is pressed
    assert fake.sent == []

    platform.release_timeout = 2.0
    threading.Timer(0.1, fake.held.clear).start()
    started = time.monotonic()
    assert platform.copy_selection(WORD)
    assert time.monotonic() - started >= 0.09
    assert fake.sent == [CTRL_INSERT]


def test_the_hotkeys_own_key_must_be_released_too():
    fake = FakeWindows()
    platform = quick_platform(fake)
    platform.start_hotkey(parse_hotkey("ctrl+shift+space"), lambda info: None)
    fake.held = {0x20}  # still holding Space
    assert not platform.copy_selection(WORD)
    platform.stop_hotkey()


def test_paste_back_into_the_original_window():
    fake = FakeWindows()
    fake.foreground = (999, "Sidekick", 1, r"C:\python\pythonw.exe")
    assert quick_platform(fake).paste_into(WORD)
    assert fake.pasted_into == [4242]
    assert fake.sent == [CTRL_V]


def test_paste_back_in_a_terminal_uses_shift_insert():
    fake = FakeWindows()
    assert quick_platform(fake).paste_into(TERMINAL)
    assert fake.sent == [SHIFT_INSERT]


def test_paste_back_is_skipped_when_unsafe():
    fake = FakeWindows()
    platform = quick_platform(fake)
    fake.foreground = (999, "Sidekick", 1, r"C:\python\pythonw.exe")
    gone = WindowInfo("Closed", "notepad.exe", 5, hwnd=5555)
    assert not platform.paste_into(gone)  # the window was closed
    assert not platform.paste_into(WindowInfo("No handle", "notepad.exe", 5))
    fake.comes_to_front = False
    assert not platform.paste_into(WORD)  # it did not come to the front
    assert fake.sent == [] and fake.pasted_into == []
