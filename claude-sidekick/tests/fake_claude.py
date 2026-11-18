"""A stand-in for the `claude` command (Claude Code), used only by the tests.

It records how it was called (to the file named in FAKE_CLAUDE_LOG), reads the
question from stdin, and prints Claude Code's stream-json lines. FAKE_CLAUDE_MODE
picks the behaviour: ok (default), old (no token-by-token events), signed_out,
slow, crash, no_safe_mode. FAKE_CLAUDE_TEXT sets the answer (pieces split by |)."""

import json
import os
import sys
import time

mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
prompt = sys.stdin.read()
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        names = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                 "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")
        billing = {k: v for k, v in os.environ.items() if k.upper() in names}
        f.write(json.dumps({"args": sys.argv[1:], "stdin": prompt, "cwd": os.getcwd(), "billing_env": billing}) + "\n")


def say(obj):
    print(json.dumps(obj), flush=True)


if mode == "no_safe_mode" and "--safe-mode" in sys.argv:
    print("error: unknown option '--safe-mode'", file=sys.stderr)
    sys.exit(1)
if mode == "crash":
    print("error: unknown option '--tools'", file=sys.stderr)
    sys.exit(1)
say({"type": "system", "subtype": "init", "model": "claude-test", "tools": []})
if mode == "signed_out":
    say({"type": "result", "subtype": "success", "is_error": True,
         "result": "Invalid API key · Please run /login"})
    sys.exit(1)
pieces = os.environ.get("FAKE_CLAUDE_TEXT", "Claude Code| says hi.").split("|")
if mode != "old":
    for piece in pieces:
        if mode == "slow":
            time.sleep(0.4)
        say({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0,
                                                 "delta": {"type": "text_delta", "text": piece}}})
say({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "".join(pieces)}]}})
say({"type": "result", "subtype": "success", "is_error": False, "result": "".join(pieces), "total_cost_usd": 0.01})
