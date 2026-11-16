"""Deciding what to put in the popup when the hotkey is pressed.

Sidekick's rule is simple: it only ever looks at what you copied (or
snipped), and only if you copied it recently. Nothing here sends anything;
the popup shows what was picked up, and you decide whether to press Ask.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable

from .attachments import Attachment, AttachmentError, attachment_from_path, image_attachment
from .config import Settings
from .platform_base import Platform, WindowInfo
from .privacy import is_private_window


class ClipboardWatch:
    """Remembers WHEN the clipboard last changed, without reading it.

    This is how Sidekick knows whether what is on the clipboard is something
    you copied just now (use it) or something old (leave it alone)."""

    def __init__(self, platform: Platform, clock: Callable[[], float] = time.monotonic):
        self._platform = platform
        self._clock = clock
        self._seq = platform.clipboard_sequence()  # whatever is there at start is "old"
        self._changed_at: float | None = None
        self.own_text: str = ""  # the last thing Sidekick itself copied

    def poll(self) -> None:
        seq = self._platform.clipboard_sequence()
        if seq is not None and seq != self._seq:
            self._seq = seq
            self._changed_at = self._clock()

    def note_own_copy(self, text: str) -> None:
        """Call right after Sidekick copies an answer, so that answer is not
        mistaken for something you copied yourself."""
        self.own_text = text
        self._seq = self._platform.clipboard_sequence()
        self._changed_at = None

    def is_fresh(self, max_age_seconds: float) -> bool:
        self.poll()
        return self._changed_at is not None and (self._clock() - self._changed_at) <= max_age_seconds


@dataclass
class Capture:
    """What the popup starts with."""

    window: WindowInfo | None = None
    private: bool = False
    text: str = ""
    attachment: Attachment | None = None
    note: str = ""  # one friendly line telling the user what happened


TIP = (
    "Tip: copy some text (Ctrl+C) or snip part of the screen (Win+Shift+S), "
    "then press the hotkey. You can also just type a question."
)


def read_clipboard(
    read_text: Callable[[], str],
    read_media: Callable[[], object],
    settings: Settings,
) -> tuple[str, Attachment | None, str]:
    """Look at the clipboard and return (text, attachment, note).

    Text wins when there is any (apps such as Excel put both text and a
    picture of the cells on the clipboard). Otherwise a picture or a copied
    file becomes the attachment."""
    text = read_text() or ""
    if text.strip():
        limit = settings.max_text_chars
        if len(text) > limit:
            return (
                text[:limit],
                None,
                f"You copied {len(text):,} characters. Sidekick kept the first {limit:,}; "
                "edit the box if you need a different part.",
            )
        return text, None, "Your copied text is in the box. Nothing is sent until you click Ask."

    media = read_media()
    if media is None:
        return "", None, "The clipboard has nothing Sidekick can use (no text, picture or file)."

    if isinstance(media, (list, tuple)):  # files copied in File Explorer
        paths = [p for p in media if isinstance(p, str) and os.path.isfile(p)]
        if not paths:
            return "", None, "The copied item is not a file Sidekick can read."
        try:
            attachment = attachment_from_path(paths[0], settings.max_image_edge)
        except AttachmentError as e:
            return "", None, str(e)
        extra = f" ({len(paths) - 1} other copied file(s) were left out.)" if len(paths) > 1 else ""
        return "", attachment, f"Attached the file you copied.{extra} Nothing is sent until you click Ask."

    try:
        attachment = image_attachment(media, "", settings.max_image_edge)
    except AttachmentError as e:
        return "", None, str(e)
    return "", attachment, "Attached the picture you copied. Nothing is sent until you click Ask."


def capture_context(
    window: WindowInfo | None,
    watch: ClipboardWatch,
    platform: Platform,
    read_text: Callable[[], str],
    read_media: Callable[[], object],
    settings: Settings,
) -> Capture:
    """Work out what the popup should show for this hotkey press."""
    if is_private_window(window, settings.private_words):
        return Capture(
            window=window,
            private=True,
            note="This looks like a private window, so Sidekick did not read your clipboard "
            "and will not send the window title. You can still type a question.",
        )

    capture = Capture(window=window)
    if not watch.is_fresh(settings.clipboard_fresh_seconds):
        capture.note = TIP
        return capture
    if platform.clipboard_marked_private():
        capture.note = (
            "The clipboard holds something marked private (often a password), "
            "so Sidekick did not read it."
        )
        return capture

    text, attachment, note = read_clipboard(read_text, read_media, settings)
    if text and text == watch.own_text:
        capture.note = TIP  # that is just the answer Sidekick copied earlier
        return capture
    capture.text, capture.attachment, capture.note = text, attachment, note
    return capture
