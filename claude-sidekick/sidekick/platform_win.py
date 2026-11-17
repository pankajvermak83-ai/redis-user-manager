"""The Windows-specific parts of Sidekick.

Only functions that are built into Windows are used (through Python's
standard `ctypes` module), so there is nothing extra to install:

  * a global hotkey, registered with Windows' own RegisterHotKey. This is
    the official way for an app to ask for a shortcut. Sidekick does NOT
    watch your keyboard and never presses keys for you;
  * the title and program name of the window you were in;
  * a counter that tells whether the clipboard changed (not what is in it);
  * a check for "this is private" markers that password managers put on
    the clipboard;
  * opening the Claude app (claude:// links), Chrome, or File Explorer.
"""

from __future__ import annotations

import ctypes
import importlib
import logging
import ntpath
import os
import subprocess
import threading
from ctypes import wintypes
from typing import Callable, Optional

from .hotkeys import Hotkey
from .platform_base import Platform, WindowInfo

log = logging.getLogger(__name__)

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x0008, 0x4000
WM_QUIT, WM_HOTKEY = 0x0012, 0x0312
PM_NOREMOVE = 0x0000
ERROR_ALREADY_EXISTS = 183
ERROR_HOTKEY_ALREADY_REGISTERED = 1409
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_SYSTEM_DPI_AWARE = 1
HOTKEY_ID = 0x5D1C  # any number of our own choosing
MUTEX_NAME = "Local\\SidekickClaudeHelper"

# Markers an app can put on the clipboard to say "tools, please ignore this".
PRIVATE_CLIPBOARD_FORMATS = (
    "ExcludeClipboardContentFromMonitorProcessing",
    "Clipboard Viewer Ignore",
)

_MOD_FLAGS = {"alt": MOD_ALT, "ctrl": MOD_CONTROL, "shift": MOD_SHIFT, "win": MOD_WIN}
_NAMED_KEYS = {
    "space": 0x20, "enter": 0x0D, "tab": 0x09, "escape": 0x1B, "insert": 0x2D,
    "delete": 0x2E, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "pause": 0x13,
}


CHROME_APP_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"


def protocol_registered(winreg, scheme: str) -> bool:
    """True if some app has told Windows it opens `scheme://` links."""
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, scheme) as key:
            winreg.QueryValueEx(key, "URL Protocol")
            return True
    except OSError:
        return False


def find_chrome(winreg, environ, isfile) -> str | None:
    """Where chrome.exe is, or None. Chrome's installer records its location
    under "App Paths"; the usual folders are checked as well."""
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, CHROME_APP_PATH) as key:
                value, _kind = winreg.QueryValueEx(key, "")
        except OSError:
            continue
        path = str(value or "").strip().strip('"')
        if path and isfile(path):
            return path
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = environ.get(var)
        if base:
            path = ntpath.join(base, "Google", "Chrome", "Application", "chrome.exe")
            if isfile(path):
                return path
    return None


def modifier_flags(hotkey: Hotkey) -> int:
    flags = 0
    for mod in hotkey.mods:
        flags |= _MOD_FLAGS[mod]
    return flags


def virtual_key(key: str) -> int:
    """Windows' number ("virtual-key code") for a key name."""
    if len(key) == 1 and key.isalnum():
        return ord(key.upper())  # letters and digits use their ASCII code
    if key in _NAMED_KEYS:
        return _NAMED_KEYS[key]
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return 0x70 + int(key[1:]) - 1  # F1 is 0x70
    raise ValueError(f"Unknown key: {key}")


class Win32Api:
    """The Windows libraries Sidekick calls into."""

    def __init__(self, user32, kernel32, shcore=None, get_last_error: Callable[[], int] = lambda: 0):
        self.user32 = user32
        self.kernel32 = kernel32
        self.shcore = shcore
        self.get_last_error = get_last_error
        _declare(self)


def load_win32() -> Win32Api:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        shcore = ctypes.WinDLL("shcore")
    except OSError:
        shcore = None  # very old Windows
    return Win32Api(user32, kernel32, shcore, ctypes.get_last_error)


def _declare(api: Win32Api) -> None:
    """Tell ctypes the exact argument and return types of each function.
    Without this, window handles could be cut off on 64-bit Windows."""
    u, k = api.user32, api.kernel32
    P = ctypes.POINTER

    def sig(fn, argtypes, restype):
        fn.argtypes = argtypes
        fn.restype = restype

    sig(u.RegisterHotKey, [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT], wintypes.BOOL)
    sig(u.UnregisterHotKey, [wintypes.HWND, ctypes.c_int], wintypes.BOOL)
    sig(u.GetMessageW, [P(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT], ctypes.c_int)
    sig(u.PeekMessageW, [P(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT], wintypes.BOOL)
    sig(u.PostThreadMessageW, [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL)
    sig(u.GetForegroundWindow, [], wintypes.HWND)
    sig(u.GetWindowTextLengthW, [wintypes.HWND], ctypes.c_int)
    sig(u.GetWindowTextW, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int)
    sig(u.GetWindowThreadProcessId, [wintypes.HWND, P(wintypes.DWORD)], wintypes.DWORD)
    sig(u.GetClipboardSequenceNumber, [], wintypes.DWORD)
    sig(u.RegisterClipboardFormatW, [wintypes.LPCWSTR], wintypes.UINT)
    sig(u.IsClipboardFormatAvailable, [wintypes.UINT], wintypes.BOOL)

    sig(k.GetCurrentThreadId, [], wintypes.DWORD)
    sig(k.OpenProcess, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE)
    sig(k.QueryFullProcessImageNameW, [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, P(wintypes.DWORD)], wintypes.BOOL)
    sig(k.CloseHandle, [wintypes.HANDLE], wintypes.BOOL)
    sig(k.CreateMutexW, [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE)

    if api.shcore is not None:
        sig(api.shcore.SetProcessDpiAwareness, [ctypes.c_int], ctypes.c_long)


class _HotkeyThread(threading.Thread):
    """Waits for Windows to say "the hotkey was pressed".

    Windows delivers that message to the thread that registered the hotkey,
    so registering and waiting both happen here, away from the window code."""

    def __init__(self, api: Win32Api, hotkey: Hotkey, on_press: Callable[[Optional[WindowInfo]], None],
                 foreground: Callable[[], Optional[WindowInfo]]):
        super().__init__(name="sidekick-hotkey", daemon=True)
        self._api = api
        self._flags = modifier_flags(hotkey) | MOD_NOREPEAT
        self._vk = virtual_key(hotkey.key)
        self._on_press = on_press
        self._foreground = foreground
        self._thread_id = 0
        self.ready = threading.Event()
        self.ok = False
        self.problem = ""

    def run(self) -> None:
        u = self._api.user32
        msg = wintypes.MSG()
        self._thread_id = self._api.kernel32.GetCurrentThreadId()
        # Looking at the queue once makes Windows create it, so that stop()
        # can reliably post to this thread.
        u.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)

        if not u.RegisterHotKey(None, HOTKEY_ID, self._flags, self._vk):
            code = self._api.get_last_error()
            self.problem = "in_use" if code == ERROR_HOTKEY_ALREADY_REGISTERED else f"error {code}"
            self.ready.set()
            return
        self.ok = True
        self.ready.set()
        try:
            while True:
                got = u.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if got == 0 or got == -1:  # WM_QUIT, or a failure
                    break
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    try:
                        # Note the window you were in right now, before
                        # Sidekick's own window comes to the front.
                        self._on_press(self._foreground())
                    except Exception:
                        log.exception("Hotkey handler failed")
        finally:
            u.UnregisterHotKey(None, HOTKEY_ID)

    def stop(self) -> None:
        if self.is_alive() and self._thread_id:
            self._api.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self.join(timeout=2.0)


class WindowsPlatform(Platform):
    name = "windows"

    def __init__(self, api: Win32Api | None = None, *, winreg=None, startfile=None,
                 popen=None, isfile=None, environ=None):
        self._api = api or load_win32()
        self._hotkey_thread: _HotkeyThread | None = None
        self._mutex = None
        # Swappable so the tests can run without Windows.
        self._winreg = winreg
        self._startfile = startfile or getattr(os, "startfile", None)
        self._popen = popen or subprocess.Popen
        self._isfile = isfile or os.path.isfile
        self._environ = environ if environ is not None else os.environ

    def _reg(self):
        if self._winreg is None:
            self._winreg = importlib.import_module("winreg")
        return self._winreg

    def prepare_process(self) -> None:
        # Makes text sharp on high-resolution screens. Harmless if it fails.
        try:
            if self._api.shcore is not None:
                self._api.shcore.SetProcessDpiAwareness(PROCESS_SYSTEM_DPI_AWARE)
        except Exception:
            pass

    def acquire_single_instance(self) -> bool:
        # A named "mutex" is how Windows apps check for a copy already running.
        self._mutex = self._api.kernel32.CreateMutexW(None, False, MUTEX_NAME)
        return self._api.get_last_error() != ERROR_ALREADY_EXISTS

    # ------------------------------------------------------------- hotkey

    def start_hotkey(self, hotkey: Hotkey, on_press: Callable[[Optional[WindowInfo]], None]) -> tuple[bool, str]:
        self.stop_hotkey()
        thread = _HotkeyThread(self._api, hotkey, on_press, self.foreground_window)
        thread.start()
        if not thread.ready.wait(timeout=3.0):
            return False, "Windows did not answer."
        if not thread.ok:
            return False, thread.problem
        self._hotkey_thread = thread
        return True, ""

    def stop_hotkey(self) -> None:
        if self._hotkey_thread is not None:
            self._hotkey_thread.stop()
            self._hotkey_thread = None

    # ------------------------------------------------------------- window

    def foreground_window(self) -> Optional[WindowInfo]:
        """Title, program name and process id of the window in front."""
        u, k = self._api.user32, self._api.kernel32
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return None
        length = u.GetWindowTextLengthW(hwnd)
        title_buf = ctypes.create_unicode_buffer(length + 1)
        u.GetWindowTextW(hwnd, title_buf, length + 1)

        pid = wintypes.DWORD(0)
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = ""
        handle = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if handle:
            try:
                size = wintypes.DWORD(1024)
                path_buf = ctypes.create_unicode_buffer(1024)
                if k.QueryFullProcessImageNameW(handle, 0, path_buf, ctypes.byref(size)):
                    exe = ntpath.basename(path_buf.value).lower()
            finally:
                k.CloseHandle(handle)
        return WindowInfo(title=title_buf.value, exe=exe, pid=int(pid.value))

    # ---------------------------------------------------------- clipboard

    def clipboard_sequence(self) -> int | None:
        return int(self._api.user32.GetClipboardSequenceNumber())

    def clipboard_marked_private(self) -> bool:
        u = self._api.user32
        for name in PRIVATE_CLIPBOARD_FORMATS:
            fmt = u.RegisterClipboardFormatW(name)
            if fmt and u.IsClipboardFormatAvailable(fmt):
                return True
        return False

    def grab_clipboard_media(self) -> object:
        try:
            from PIL import ImageGrab

            return ImageGrab.grabclipboard()  # a picture, a list of files, or None
        except Exception as e:
            log.warning("Could not read a picture from the clipboard: %s", type(e).__name__)
            return None

    # ------------------------------------------------- Claude app / website

    def claude_app_installed(self) -> bool:
        return protocol_registered(self._reg(), "claude")

    def open_link(self, url: str) -> bool:
        """Open a link the way double-clicking it would: claude:// links go to
        the Claude app, https:// links to your usual browser."""
        if self._startfile is None:
            return False
        try:
            self._startfile(url)
            return True
        except OSError as e:
            log.warning("Could not open a %s link: %s", url.split(":", 1)[0], e)
            return False

    def open_in_chrome(self, url: str) -> bool:
        chrome = find_chrome(self._reg(), self._environ, self._isfile)
        if chrome is None:
            return False
        try:
            self._popen([chrome, url])
            return True
        except OSError as e:
            log.warning("Could not start Chrome: %s", e)
            return False

    def reveal_file(self, path: str) -> bool:
        if '"' in path:  # never happens on Windows; keeps the command line safe
            return False
        try:
            # Explorer wants exactly this form: /select,"C:\folder\file.pdf"
            self._popen(f'explorer /select,"{path}"')
            return True
        except OSError as e:
            log.warning("Could not open File Explorer: %s", e)
            return False
