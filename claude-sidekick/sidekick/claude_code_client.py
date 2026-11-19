"""Answering with Claude Code: Anthropic's own command-line tool.

Claude Code signs in with your Claude plan (Pro, Max, ...), so answers
come with no API key and no separate bill. Sidekick runs its documented
scripted mode, `claude -p`, like this:

  * all of Claude Code's tools are switched off (--tools ""), so it can't run
    commands or open files: it only answers;
  * it runs in an empty folder of Sidekick's own and loads no MCP servers;
  * safe mode (--safe-mode) keeps your own CLAUDE.md files, hooks, plugins,
    skills and auto memory out of it; sign-in works as usual;
  * nothing is saved as a session (--no-session-persistence);
  * API-key settings are removed from its environment: Anthropic's docs say
    that in this mode an ANTHROPIC_API_KEY, if present, is always used and
    billed per use, even when you are signed in with your Claude plan;
  * the question goes in through stdin as one JSON message, so pictures and
    PDFs can go with it (--input-format stream-json), and the answer streams
    back as JSON lines (--output-format stream-json --include-partial-messages).

Sidekick never touches your Claude login itself: Claude Code does that.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .claude_client import AskError, AskResult, Conversation
from .config import config_dir
from .prompts import SYSTEM_PROMPT

log = logging.getLogger(__name__)

NOT_INSTALLED = (
    "Claude Code was not found on this PC (the \"claude\" command). The VS Code extension has its own "
    "copy, which Sidekick can't use: install Claude Code for the terminal from code.claude.com (in "
    "PowerShell: irm https://claude.ai/install.ps1 | iex), run claude once to sign in, then restart "
    "Sidekick. Or choose another AI service in Settings."
)
NOT_SIGNED_IN = (
    "Claude Code is not signed in. Open a terminal, run claude, and sign in with your Claude account. "
    "Then try again."
)
# Settings that would make Claude Code bill an API account or a cloud
# provider instead of your Claude plan. Sidekick's "your Claude plan" mode
# removes them from Claude Code's environment.
BILLING_OVERRIDES = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
)


def plan_only_environment(environ: dict | None = None) -> dict:
    """A copy of the environment without anything that would bill an API
    account, so Claude Code uses your Claude plan's sign-in."""
    env = dict(os.environ if environ is None else environ)
    for name in list(env):
        if name.upper() in BILLING_OVERRIDES:
            del env[name]
    return env


def find_claude(configured: str = "") -> str | None:
    """Where the `claude` command is: the path set in Settings, the PATH, or
    the folder Anthropic's Windows installer uses."""
    candidates = [configured, shutil.which("claude"),
                  os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def split_content(content: object) -> tuple[list[dict], str]:
    """A message's pictures and PDFs, and its words."""
    if isinstance(content, str):
        return [], content
    media, texts = [], []
    for block in content if isinstance(content, list) else []:
        kind = block.get("type") if isinstance(block, dict) else None
        if kind == "text":
            texts.append(block["text"])
        elif kind in ("image", "document"):
            media.append(block)
    return media, "\n\n".join(texts)


def stdin_message(media: list[dict], prompt: str) -> str:
    """The one line Claude Code reads from stdin: a user message in its
    stream-json format. Pictures and PDFs go first, then the words."""
    content = list(media) + [{"type": "text", "text": prompt}]
    return json.dumps({
        "type": "user", "message": {"role": "user", "content": content},
        "parent_tool_use_id": None, "session_id": "default",
    }) + "\n"


def build_prompt(conversation: Conversation, new_message: str) -> str:
    """Each run starts fresh, so follow-up questions carry the conversation so far."""
    if not conversation.messages:
        return new_message
    lines = ["Here is our conversation so far:"]
    for message in conversation.messages:
        who = "Me" if message["role"] == "user" else "You"
        lines.append(f"\n[{who}]\n{message['content']}")
    lines.append(f"\nMy next message:\n{new_message}")
    return "\n".join(lines)


def _stop(process: subprocess.Popen) -> None:
    """End Claude Code. On Windows, `claude` may be a small claude.cmd file
    (an npm install) that starts the real program: end that one too."""
    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True,
                           timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        process.kill()
    except OSError:
        pass  # it has already ended


@dataclass
class _Run:
    cancelled: bool = False
    final: dict | None = None
    pieces: list = field(default_factory=list)
    whole_answer: str = ""
    errors: str = ""


class ClaudeCodeClient:
    def __init__(self, settings, command: list[str] | None = None, *, workdir: Path | None = None,
                 timeout: float = 180.0):
        self._settings = settings
        self._command = command
        self._workdir = workdir or (config_dir() / "claude-code")
        self._timeout = timeout
        self._safe_mode = True  # switched off only for Claude Code versions without it

    model = property(lambda self: self._settings.claude_code_model or "Claude Code")

    def has_credentials(self) -> bool:
        return True  # Claude Code checks its own sign-in

    def count_input_tokens(self, conversation: Conversation, user_content: object) -> int | None:
        return None

    def _base_command(self) -> list[str]:
        if self._command:
            return list(self._command)
        path = find_claude(self._settings.claude_code_command)
        if not path:
            raise AskError(NOT_INSTALLED)
        return [path]

    def _arguments(self, prompt_file: Path) -> list[str]:
        args = self._base_command() + [
            "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--include-partial-messages",
            "--system-prompt-file", str(prompt_file), "--tools", "", "--strict-mcp-config",
            "--max-turns", "1", "--no-session-persistence",
        ]
        if self._safe_mode:
            # Your own CLAUDE.md files, hooks, plugins, skills and auto memory
            # are for your coding: keep them out of Sidekick's questions.
            args.append("--safe-mode")
        if self._settings.claude_code_model:
            args += ["--model", self._settings.claude_code_model]
        return args

    def ask(
        self,
        conversation: Conversation,
        user_content: object,
        on_text: Callable[[str], None],
        should_stop: Callable[[], bool] = lambda: False,
    ) -> AskResult:
        media, new_message = split_content(user_content)
        # Each run starts fresh, so pictures and PDFs from earlier in the
        # conversation are sent again with the conversation so far.
        earlier = [block for message in conversation.messages for block in message.get("media", [])]
        prompt = stdin_message(earlier + media, build_prompt(conversation, new_message))
        self._workdir.mkdir(parents=True, exist_ok=True)
        prompt_file = self._workdir / "sidekick-instructions.txt"
        prompt_file.write_text(SYSTEM_PROMPT, encoding="utf-8")

        run = self._run(prompt_file, prompt, on_text, should_stop)
        if self._safe_mode and run.final is None and "--safe-mode" in run.errors and "unknown option" in run.errors.lower():
            # An older Claude Code without safe mode: ask again without it.
            log.warning("This Claude Code has no --safe-mode; continuing without it")
            self._safe_mode = False
            run = self._run(prompt_file, prompt, on_text, should_stop)
        if run.cancelled:
            return AskResult(cancelled=True)

        final = run.final
        if final is None or final.get("is_error"):
            said = str((final or {}).get("result") or run.errors).strip()
            low = said.lower()
            if any(word in low for word in ("login", "log in", "sign in", "api key", "authenticat")):
                raise AskError(NOT_SIGNED_IN)
            if "unknown option" in low or "unrecognized" in low:
                raise AskError("Your Claude Code is too old for Sidekick. Update it (run: claude update) and try again.")
            raise AskError(f"Claude Code reported a problem: {said[-400:] or 'it stopped without an answer.'}")

        text = "".join(run.pieces)
        if not text and run.whole_answer:  # older Claude Code: no token-by-token updates
            text = run.whole_answer
            on_text(text)
        if not text and isinstance(final.get("result"), str):
            text = final["result"]
            on_text(text)
        result = AskResult(text=text, stop_reason=final.get("subtype"), model=self.model)
        if not text.strip():
            result.notice = "Claude Code sent back an empty answer. Try asking again."
        user_message = {"role": "user", "content": new_message}
        if media:
            user_message["media"] = media
        conversation.messages.append(user_message)
        conversation.messages.append({"role": "assistant", "content": text})
        return result

    def _run(self, prompt_file: Path, prompt: str, on_text, should_stop) -> "_Run":
        """Start Claude Code once and collect what it prints."""
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        try:
            process = subprocess.Popen(
                self._arguments(prompt_file), cwd=str(self._workdir), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags,
                env=plan_only_environment(),
            )
        except FileNotFoundError as e:
            raise AskError(NOT_INSTALLED) from e
        except OSError as e:
            raise AskError(f"Claude Code could not be started ({e}).") from e

        lines: queue.Queue = queue.Queue()
        errors: list[bytes] = []

        def read_out():
            for raw in process.stdout:
                lines.put(raw)
            lines.put(None)

        def read_err():
            errors.append(process.stderr.read())

        threading.Thread(target=read_out, daemon=True).start()
        err_thread = threading.Thread(target=read_err, daemon=True)
        err_thread.start()
        try:
            process.stdin.write(prompt.encode("utf-8"))
            process.stdin.close()
        except OSError:
            pass  # it already stopped; the reason shows below

        run = _Run()
        deadline = time.monotonic() + self._timeout
        try:
            while True:
                if should_stop():
                    run.cancelled = True
                    return run
                if time.monotonic() > deadline:
                    raise AskError("Claude Code stopped responding. Try again.")
                try:
                    raw = lines.get(timeout=0.1)
                except queue.Empty:
                    continue
                if raw is None:
                    break
                deadline = time.monotonic() + self._timeout  # still answering: wait on
                try:
                    event = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                kind = event.get("type")
                if kind == "stream_event":
                    delta = (event.get("event") or {}).get("delta") or {}
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        run.pieces.append(delta["text"])
                        on_text(delta["text"])
                elif kind == "assistant":
                    content = (event.get("message") or {}).get("content") or []
                    run.whole_answer += "".join(
                        b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
                elif kind == "result":
                    run.final = event
        finally:
            if process.poll() is None:
                _stop(process)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            err_thread.join(timeout=2)
            run.errors = b"".join(errors).decode("utf-8", "replace")
        return run
