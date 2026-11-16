"""What Sidekick needs from the operating system.

`Platform` here is the do-nothing version. It is used on non-Windows
computers (for development) and as the base for the real Windows version in
platform_win.py.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable, Optional

from .hotkeys import Hotkey


@dataclass(frozen=True)
class WindowInfo:
    """The window you were working in when you pressed the hotkey."""

    title: str = ""
    exe: str = ""  # program file name in lower case, e.g. "excel.exe"
    pid: int = 0

    def app_name(self) -> str:
        name = self.exe[:-4] if self.exe.endswith(".exe") else self.exe
        return name.capitalize() if name.islower() else name

    def describe(self, limit: int = 70) -> str:
        parts = [p for p in (self.app_name(), self.title) if p]
        text = " — ".join(parts) if parts else "(unknown window)"
        return text if len(text) <= limit else text[: limit - 1] + "…"


class Platform:
    name = "generic"

    def prepare_process(self) -> None:
        """One-time setup before any window is created."""

    def acquire_single_instance(self) -> bool:
        """False if another copy of Sidekick is already running."""
        return True

    def start_hotkey(self, hotkey: Hotkey, on_press: Callable[[Optional[WindowInfo]], None]) -> tuple[bool, str]:
        """Start listening for the global hotkey. `on_press` is called on a
        background thread. Returns (worked, reason-if-not)."""
        return False, "unsupported"

    def stop_hotkey(self) -> None:
        pass

    def clipboard_sequence(self) -> int | None:
        """A number that changes whenever the clipboard changes (or None if
        this system cannot tell). The clipboard itself is not read."""
        return None

    def clipboard_marked_private(self) -> bool:
        """True if the app that copied the data asked that clipboard tools
        ignore it. Password managers do this."""
        return False

    def grab_clipboard_media(self) -> object:
        """A PIL image, a list of file paths, or None."""
        return None


def get_platform() -> Platform:
    if sys.platform == "win32":
        from .platform_win import WindowsPlatform

        return WindowsPlatform()
    return Platform()
