"""Sending a question to the official Claude app or website instead of the API.

Anthropic documents a link that opens the Claude desktop app with a new
chat whose question box is already filled in:

    claude://claude.ai/new?q=<the question, URL-encoded>

You check the question and press Enter yourself, so it runs on your normal
Claude plan (Free, Pro, Max, ...) and there is no API bill. Sidekick never
uses your Claude login itself: Anthropic's terms do not allow other apps to
do that, and this link is the official way in.

Things a link cannot carry are handed over through the clipboard:
  * long text (links over a safe length): Sidekick copies it; you press Ctrl+V,
  * a picture you snipped: it is already on the clipboard; you press Ctrl+V,
  * a file from disk: Sidekick shows it in File Explorer; you drag it in.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field

from .attachments import Attachment
from .platform_base import WindowInfo

APP_NEW_CHAT = "claude://claude.ai/new"
WEB_NEW_CHAT = "https://claude.ai/new"

# Links longer than this are not used to carry text. Very long links are not
# reliable everywhere on Windows, and Claude cuts the text at about 14,000
# characters anyway. Longer questions go through the clipboard instead.
MAX_LINK_LENGTH = 2000

TARGET_NAMES = {"claude_app": "the Claude app", "chrome": "Chrome", "browser": "your web browser"}


def build_chat_prompt(
    question: str,
    copied_text: str = "",
    window: WindowInfo | None = None,
    attachment: Attachment | None = None,
) -> str:
    """The question as it will appear in Claude's chat box: plain, readable
    text, because you will see it (and can edit it) before it is sent."""
    parts: list[str] = []
    if window is not None and (window.exe or window.title):
        app, title = window.app_name() or "an app", window.title
        parts.append(f'I am working in {app}, in the window "{title}".' if title else f"I am working in {app}.")
    if attachment is not None and attachment.kind == "text":
        parts.append(f'Here is the file "{attachment.name}":\n"""\n{attachment.text().strip()}\n"""')
    if copied_text.strip():
        parts.append(f'Here is what I copied:\n"""\n{copied_text.strip()}\n"""')
    parts.append(question.strip())
    return "\n\n".join(parts)


def chat_link(base: str, prompt: str | None) -> str:
    if not prompt:
        return base
    return f"{base}?q={urllib.parse.quote(prompt, safe='')}"


@dataclass
class HandoffPlan:
    target: str  # "claude_app" or "chrome"
    url: str  # the link to open
    clipboard_text: str | None = None  # text Sidekick puts on the clipboard first
    reveal_file: str | None = None  # a file to show in File Explorer
    steps: list[str] = field(default_factory=list)  # what the user does in Claude


def plan_handoff(
    send_to: str,
    prompt: str,
    attachment: Attachment | None = None,
    attachment_path: str | None = None,
    picture_on_clipboard: bool = False,
) -> HandoffPlan:
    """Decide how this question travels to Claude, and what the user does next.

    `picture_on_clipboard` means the attachment is a picture that is still on
    the clipboard (a snip), so Ctrl+V in Claude adds it."""
    target = "chrome" if send_to == "chrome" else "claude_app"
    base = WEB_NEW_CHAT if target == "chrome" else APP_NEW_CHAT
    picture = attachment is not None and attachment.kind == "image" and picture_on_clipboard
    file_on_disk = attachment is not None and attachment.kind in ("image", "pdf") and not picture
    plan = HandoffPlan(target=target, url=base)

    # The website's prefill is not documented by Anthropic, and a link stays
    # in the browser's history. So for Chrome the text goes through the
    # clipboard, unless the clipboard is needed for a snipped picture.
    link = chat_link(base, prompt)
    use_link = len(link) <= MAX_LINK_LENGTH and (target == "claude_app" or picture)

    if use_link:
        plan.url = link
    elif picture:
        # Text too long for a link, and the clipboard holds the picture:
        # the text wins; the user snips the picture again afterwards.
        plan.clipboard_text = prompt
        plan.steps.append("Press Ctrl+V to paste your question.")
        plan.steps.append("Your picture was replaced on the clipboard: press Win+Shift+S, snip it again, then press Ctrl+V.")
        picture = False
    else:
        plan.clipboard_text = prompt
        plan.steps.append("Press Ctrl+V to paste your question.")

    if picture:
        plan.steps.append("Press Ctrl+V to add your picture.")
    if file_on_disk and attachment_path:
        plan.reveal_file = attachment_path
        plan.steps.append(f'Drag "{attachment.name}" from the File Explorer window into Claude.')
    if use_link and target == "chrome":
        plan.steps.append("If the question box is empty, type your question.")
    plan.steps.append("Check the question, then press Enter.")
    return plan
