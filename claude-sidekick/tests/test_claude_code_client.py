"""Tests for answers from Claude Code (`claude -p`), using a stand-in program."""

import json
import os
import sys
import time

import pytest

from sidekick.attachments import Attachment
from sidekick.claude_client import AskError, Conversation
from sidekick.claude_code_client import (
    NO_PICTURES, NOT_INSTALLED, NOT_SIGNED_IN, ClaudeCodeClient, plan_only_environment,
)
from sidekick.config import Settings
from sidekick.prompts import TEXT_ONLY_SYSTEM_PROMPT

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_claude.py")


@pytest.fixture
def run(tmp_path, monkeypatch):
    """Ask through the stand-in and return (result, pieces, calls)."""
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))

    def go(content="Why is the sky blue?", mode="ok", convo=None, stop=lambda: False, **settings):
        monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
        c = ClaudeCodeClient(Settings(**settings), command=[sys.executable, FAKE], workdir=tmp_path / "room")
        pieces = []
        result = c.ask(convo if convo is not None else Conversation(), content, pieces.append, stop)
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, pieces, calls

    return go


def test_answer_streams_from_claude_code(run, tmp_path):
    result, pieces, calls = run()
    assert pieces == ["Claude Code", " says hi."]
    assert result.text == "Claude Code says hi." and result.notice == ""
    call, = calls
    assert call["stdin"] == "Why is the sky blue?"
    assert call["cwd"] == str(tmp_path / "room")  # an empty folder of Sidekick's own
    args = call["args"]
    for flag in ("-p", "--verbose", "--include-partial-messages", "--strict-mcp-config",
                 "--no-session-persistence", "--safe-mode"):
        assert flag in args
    assert args[args.index("--output-format") + 1] == "stream-json"
    assert args[args.index("--tools") + 1] == ""  # every tool switched off
    assert args[args.index("--max-turns") + 1] == "1"
    instructions = args[args.index("--system-prompt-file") + 1]
    assert open(instructions, encoding="utf-8").read() == TEXT_ONLY_SYSTEM_PROMPT
    assert "Win+Shift+S" not in TEXT_ONLY_SYSTEM_PROMPT  # Claude Code can't take a snip
    assert "--model" not in args


def test_model_choice_is_passed_on(run):
    _, _, (call,) = run(claude_code_model="haiku")
    assert call["args"][call["args"].index("--model") + 1] == "haiku"


def test_follow_ups_include_the_conversation(run):
    convo = Conversation()
    run("What is 2+2?", convo=convo)
    _, _, calls = run("And doubled?", convo=convo)
    prompt = calls[-1]["stdin"]
    assert prompt.startswith("Here is our conversation so far:")
    assert "[Me]\nWhat is 2+2?" in prompt and "[You]\nClaude Code says hi." in prompt
    assert prompt.endswith("My next message:\nAnd doubled?")


def test_older_claude_code_without_token_updates(run):
    result, pieces, _ = run(mode="old")
    assert result.text == "Claude Code says hi." and pieces == ["Claude Code says hi."]


@pytest.mark.parametrize("mode, expected", [
    ("signed_out", NOT_SIGNED_IN),
    ("crash", "too old for Sidekick"),
])
def test_problems_are_explained(run, mode, expected):
    convo = Conversation()
    with pytest.raises(AskError) as caught:
        run(mode=mode, convo=convo)
    assert expected in str(caught.value)
    assert convo.messages == []


def test_stop_button_ends_claude_code(run):
    started = time.monotonic()
    result, pieces, _ = run(mode="slow", stop=lambda: time.monotonic() - started > 0.2)
    assert result.cancelled and pieces == []
    assert time.monotonic() - started < 3  # Claude Code was stopped, not waited for


def test_pictures_are_not_sent_to_claude_code(run):
    picture = Attachment("image", "", "image/png", b"png")
    content = [picture.content_block(), {"type": "text", "text": "What is this?"}]
    with pytest.raises(AskError) as caught:
        run(content)
    assert str(caught.value) == NO_PICTURES


def test_not_installed(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))  # no `claude` anywhere
    # ...not even where Anthropic's Windows installer puts it (~\.local\bin)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    c = ClaudeCodeClient(Settings(), workdir=tmp_path / "room")
    with pytest.raises(AskError) as caught:
        c.ask(Conversation(), "hi", lambda _t: None)
    assert str(caught.value) == NOT_INSTALLED


def test_api_keys_are_removed_so_your_plan_is_used(run, monkeypatch):
    # Anthropic: in -p mode an ANTHROPIC_API_KEY is always used (and billed) when present
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-be-used")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example.com")
    _, _, (call,) = run()
    assert call["billing_env"] == {}


def test_plan_only_environment_keeps_everything_else():
    env = plan_only_environment({"PATH": "C:\\bin", "anthropic_api_key": "x", "HOME": "h"})
    assert env == {"PATH": "C:\\bin", "HOME": "h"}


def test_older_claude_code_without_safe_mode(tmp_path, monkeypatch):
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "no_safe_mode")
    c = ClaudeCodeClient(Settings(), command=[sys.executable, FAKE], workdir=tmp_path / "room")
    result = c.ask(Conversation(), "hi", lambda _t: None)
    assert result.text == "Claude Code says hi."
    c.ask(Conversation(), "again", lambda _t: None)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert ["--safe-mode" in call["args"] for call in calls] == [True, False, False]


def test_a_long_answer_is_not_cut_off_while_it_keeps_coming(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "slow")  # a piece every 0.4 s
    monkeypatch.setenv("FAKE_CLAUDE_TEXT", "One|Two|Three")
    c = ClaudeCodeClient(Settings(), command=[sys.executable, FAKE], workdir=tmp_path / "room", timeout=0.9)
    assert c.ask(Conversation(), "hi", lambda _t: None).text == "OneTwoThree"  # 1.2 s in all


def test_claude_code_that_goes_silent_is_stopped(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "slow")
    c = ClaudeCodeClient(Settings(), command=[sys.executable, FAKE], workdir=tmp_path / "room", timeout=0.2)
    with pytest.raises(AskError) as caught:
        c.ask(Conversation(), "hi", lambda _t: None)
    assert "stopped responding" in str(caught.value)
