"""The privacy guard: decide what Sidekick must not read or send.

Two simple checks, both done on your PC before anything goes to the internet:

1. Was the window you were in a private one (password manager, bank,
   private browsing, a sign-in screen)? Then Sidekick reads nothing.
2. Does the text you are about to send look like it contains a secret
   (a password, an API key, a card number)? Then Sidekick asks you first.
"""

from __future__ import annotations

import re

from .platform_base import WindowInfo


def is_private_window(window: WindowInfo | None, private_words: list[str]) -> bool:
    """True if the window's program name or title contains a private word."""
    if window is None:
        return False
    haystack = f"{window.exe} {window.title}".lower()
    return any(word and word.lower() in haystack for word in private_words)


_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("an API key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("an API key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("an access token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("a password", re.compile(r"(?i)\b(?:password|passwd|pwd|passcode)\s*[:=]\s*\S+")),
]
_DIGIT_RUN = re.compile(r"(?<![\d.])(?:\d[ -]?){12,18}\d(?![\d.])")


def _luhn_ok(digits: str) -> bool:
    """The checksum that real payment card numbers pass."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def find_secrets(text: str) -> list[str]:
    """Kinds of secrets the text seems to contain, e.g. ["a password"].
    An empty list means nothing suspicious was found. This is a helpful
    warning, not a guarantee."""
    found: list[str] = []
    for label, pattern in _SECRET_PATTERNS:
        if label not in found and pattern.search(text):
            found.append(label)
    for match in _DIGIT_RUN.finditer(text):
        digits = re.sub(r"[ -]", "", match.group())
        if 13 <= len(digits) <= 19 and len(set(digits)) > 1 and _luhn_ok(digits):
            found.append("a card number")
            break
    return found
