"""A tiny stand-in for the Anthropic API, used only by the tests.

It runs on this computer, records every request Sidekick sends, and replies
with whatever the test scripted. No real API key is used and nothing leaves
the machine."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def sse_events(
    text_chunks=("Hello", " there"),
    *,
    model="claude-opus-5-5",
    stop_reason="end_turn",
    thinking=True,
    input_tokens=120,
    output_tokens=45,
    stop_details=None,
    fallback_to=None,
    iterations=None,
):
    """Build the list of streaming events for one reply."""
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_test", "type": "message", "role": "assistant", "model": model,
                "content": [], "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": input_tokens, "output_tokens": 1},
            },
        }
    ]
    index = 0
    if thinking:
        events += [
            {"type": "content_block_start", "index": index, "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
            {"type": "content_block_delta", "index": index, "delta": {"type": "signature_delta", "signature": "sig-abc"}},
            {"type": "content_block_stop", "index": index},
        ]
        index += 1
    if fallback_to:
        events += [
            {
                "type": "content_block_start", "index": index,
                "content_block": {
                    "type": "fallback", "from": {"model": "claude-opus-5-5"}, "to": {"model": fallback_to},
                    "trigger": {"type": "refusal", "category": "cyber"},
                },
            },
            {"type": "content_block_stop", "index": index},
        ]
        index += 1
        events += [
            {"type": "content_block_start", "index": index, "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
            {"type": "content_block_delta", "index": index, "delta": {"type": "signature_delta", "signature": "sig-fallback"}},
            {"type": "content_block_stop", "index": index},
        ]
        index += 1
    if text_chunks:
        events.append({"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}})
        for chunk in text_chunks:
            events.append({"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": chunk}})
        events.append({"type": "content_block_stop", "index": index})
    delta = {"stop_reason": stop_reason, "stop_sequence": None}
    if stop_details is not None:
        delta["stop_details"] = stop_details
    usage = {"output_tokens": output_tokens}
    if iterations is not None:
        usage["iterations"] = iterations
    events.append({"type": "message_delta", "delta": delta, "usage": usage})
    events.append({"type": "message_stop"})
    return events


def api_error(status, kind, message):
    return ("error", status, {"type": "error", "error": {"type": kind, "message": message}})


class FakeAnthropic:
    def __init__(self):
        self.requests = []  # every /v1/messages request: {"path", "headers", "body"}
        self.count_requests = []
        self.script = []  # replies to hand out, in order
        self.count_reply = {"input_tokens": 1234}
        self.event_delay = 0.0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # keep test output quiet
                pass

            def _json(self, status, payload):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                record = {"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body}
                if self.path.startswith("/v1/messages/count_tokens"):
                    owner.count_requests.append(record)
                    if isinstance(owner.count_reply, tuple):
                        _, status, payload = owner.count_reply
                        return self._json(status, payload)
                    return self._json(200, owner.count_reply)

                owner.requests.append(record)
                reply = owner.script.pop(0) if owner.script else sse_events()
                if isinstance(reply, tuple) and reply[0] == "error":
                    return self._json(reply[1], reply[2])

                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    for event in reply:
                        chunk = f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        if owner.event_delay:
                            time.sleep(owner.event_delay)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the client hung up (for example the user pressed Stop)
                self.close_connection = True

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._server.shutdown()
        self._server.server_close()
