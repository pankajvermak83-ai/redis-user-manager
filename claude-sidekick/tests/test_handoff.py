"""Tests for handing a question to the Claude app or website (no API key)."""

import urllib.parse

from sidekick.attachments import Attachment
from sidekick.handoff import (
    APP_NEW_CHAT, MAX_LINK_LENGTH, WEB_NEW_CHAT, build_chat_prompt, chat_link, plan_handoff,
)
from sidekick.platform_base import WindowInfo

EXCEL = WindowInfo("Budget.xlsx - Excel", "excel.exe", 1)
SNIP = Attachment("image", "", "image/png", b"png-bytes", "10 x 10")
PDF = Attachment("pdf", "report.pdf", "application/pdf", b"%PDF", "1 KB", path=r"C:\Docs\report.pdf")
DONE = "Check the question, then press Enter."


def q(url):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["q"][0]


def test_question_reads_naturally():
    assert build_chat_prompt("Why?", "=SUM(A1", EXCEL) == (
        'I am working in Excel, in the window "Budget.xlsx - Excel".\n\n'
        'Here is what I copied:\n"""\n=SUM(A1\n"""\n\nWhy?'
    )
    assert build_chat_prompt("  Hi  ") == "Hi"
    assert build_chat_prompt("Hi", window=WindowInfo("", "notepad.exe")) == "I am working in Notepad.\n\nHi"
    note = Attachment("text", "notes.txt", "text/plain", b"line one\n")
    assert build_chat_prompt("Summarize", attachment=note) == (
        'Here is the file "notes.txt":\n"""\nline one\n"""\n\nSummarize'
    )


def test_links_are_fully_encoded():
    text = 'Fix "this"/that & more\nnew line + caf\u00e9 100%'
    url = chat_link(APP_NEW_CHAT, text)
    assert url.startswith("claude://claude.ai/new?q=")
    encoded = url.split("?q=", 1)[1]
    assert not any(ch in encoded for ch in ' \n&/"+')
    assert q(url) == text
    assert chat_link(WEB_NEW_CHAT, "") == WEB_NEW_CHAT


def test_short_question_rides_in_the_app_link():
    plan = plan_handoff("claude_app", "What is 2+2?")
    assert plan.target == "claude_app"
    assert q(plan.url) == "What is 2+2?"
    assert plan.clipboard_text is None and plan.reveal_file is None
    assert plan.steps == [DONE]


def test_long_question_goes_through_the_clipboard():
    prompt = "x " * 1500
    plan = plan_handoff("claude_app", prompt)
    assert plan.url == APP_NEW_CHAT
    assert plan.clipboard_text == prompt
    assert plan.steps == ["Press Ctrl+V to paste your question.", DONE]


def test_length_limit_counts_the_encoded_link():
    prompt = "\u00e9" * 400  # short as text, about 2,400 characters once encoded
    assert len(prompt) < MAX_LINK_LENGTH < len(chat_link(APP_NEW_CHAT, prompt))
    assert plan_handoff("claude_app", prompt).clipboard_text == prompt


def test_chrome_uses_the_clipboard_unless_a_picture_needs_it():
    plan = plan_handoff("chrome", "Hello")
    assert plan.target == "chrome"
    assert plan.url == WEB_NEW_CHAT and plan.clipboard_text == "Hello"

    plan = plan_handoff("chrome", "What is this?", SNIP, None, picture_on_clipboard=True)
    assert q(plan.url) == "What is this?" and plan.clipboard_text is None
    assert plan.steps == [
        "Press Ctrl+V to add your picture.",
        "If the question box is empty, type your question.",
        DONE,
    ]


def test_snipped_picture_with_a_long_question():
    prompt = "x " * 1500
    plan = plan_handoff("claude_app", prompt, SNIP, None, picture_on_clipboard=True)
    assert plan.clipboard_text == prompt
    assert any("snip it again" in step for step in plan.steps)
    assert "Press Ctrl+V to add your picture." not in plan.steps


def test_files_on_disk_are_dragged_in():
    plan = plan_handoff("claude_app", "Summarize this", PDF, PDF.path)
    assert plan.reveal_file == r"C:\Docs\report.pdf"
    assert q(plan.url) == "Summarize this"
    assert plan.steps == ['Drag "report.pdf" from the File Explorer window into Claude.', DONE]

    picture_file = Attachment("image", "chart.png", "image/png", b"png", path=r"C:\chart.png")
    assert plan_handoff("claude_app", "Explain", picture_file, picture_file.path).reveal_file == r"C:\chart.png"


def test_text_files_need_no_dragging():
    note = Attachment("text", "notes.txt", "text/plain", b"abc", path=r"C:\notes.txt")
    assert plan_handoff("claude_app", "Summarize", note, note.path).reveal_file is None
