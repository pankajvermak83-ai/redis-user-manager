"""Turning text like "ctrl+shift+space" into a hotkey and back."""

from __future__ import annotations

from dataclasses import dataclass

MODIFIER_ORDER = ("ctrl", "alt", "shift", "win")
_ALIASES = {
    "control": "ctrl", "ctl": "ctrl", "option": "alt", "windows": "win", "super": "win",
    "spacebar": "space", "return": "enter", "esc": "escape", "pgup": "pageup",
    "pgdn": "pagedown", "ins": "insert", "del": "delete",
}
_NAMED_KEYS = {
    "space", "enter", "tab", "escape", "insert", "delete", "home", "end",
    "pageup", "pagedown", "pause",
}


@dataclass(frozen=True)
class Hotkey:
    mods: frozenset  # some of "ctrl", "alt", "shift", "win"
    key: str  # "space", "a", "7", "f9", ...

    def __str__(self) -> str:
        parts = [m for m in MODIFIER_ORDER if m in self.mods] + [self.key]
        return "+".join(parts)

    def pretty(self) -> str:
        """For showing to people: Ctrl+Shift+Space."""
        def cap(p: str) -> str:
            if len(p) == 1 or (p.startswith("f") and p[1:].isdigit()):
                return p.upper()
            return {"pageup": "PageUp", "pagedown": "PageDown"}.get(p, p.capitalize())

        parts = [m for m in MODIFIER_ORDER if m in self.mods] + [self.key]
        return "+".join(cap(p) for p in parts)


def is_valid_key(key: str) -> bool:
    if len(key) == 1:
        return key.isascii() and key.isalnum()
    if key in _NAMED_KEYS:
        return True
    if key.startswith("f") and key[1:].isdigit():
        return 1 <= int(key[1:]) <= 24
    return False


def parse_hotkey(text: str) -> Hotkey:
    """Parse "Ctrl + Shift + Space". Raises ValueError with a plain-English
    reason if the text cannot be used as a hotkey."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("The hotkey is empty.")
    parts = [p.strip().lower() for p in text.replace(" ", "").split("+")]
    if any(not p for p in parts):
        raise ValueError("Write the hotkey like this: ctrl+shift+space")
    parts = [_ALIASES.get(p, p) for p in parts]

    mods = set()
    keys = []
    for p in parts:
        if p in MODIFIER_ORDER:
            mods.add(p)
        else:
            keys.append(p)
    if len(keys) != 1:
        raise ValueError("A hotkey needs exactly one normal key, for example ctrl+shift+space.")
    key = keys[0]
    if not is_valid_key(key):
        raise ValueError(f"'{key}' cannot be used. Use a letter, a number, space or F1 to F24.")
    if not (mods & {"ctrl", "alt", "win"}):
        # Shift+A alone would fire every time you type a capital A.
        raise ValueError("Add Ctrl, Alt or Win to the hotkey, for example ctrl+shift+space.")
    return Hotkey(frozenset(mods), key)
