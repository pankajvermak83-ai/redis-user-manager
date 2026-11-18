"""A tiny stand-in for an OpenAI-compatible chat service (Gemini, Ollama, ...),
used only by the tests. It records each request and replies with scripted
streaming answers. Nothing leaves this computer."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def chunks(pieces=("Hello", " there"), *, finish="stop", usage=None, model="test-model"):
    """The stream for one answer."""
    events = [{"id": "c1", "object": "chat.completion.chunk", "model": model,
               "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]}]
    for piece in pieces:
        events.append({"id": "c1", "object": "chat.completion.chunk", "model": model,
                       "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]})
    last = {"id": "c1", "object": "chat.completion.chunk", "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}
    if usage is not None:
        last["usage"] = usage
    events.append(last)
    return events


def error(status, message, as_list=False):
    body = {"error": {"code": status, "message": message, "status": "ERROR"}}
    return ("error", status, [body] if as_list else body)


class FakeCompat:
    def __init__(self):
        self.requests = []  # {"path", "headers", "body"}
        self.script = []
        self.event_delay = 0.0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                owner.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                                       "body": body})
                reply = owner.script.pop(0) if owner.script else chunks()
                if isinstance(reply, tuple) and reply[0] == "error":
                    data = json.dumps(reply[2]).encode()
                    self.send_response(reply[1])
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    for event in reply:
                        line = event if isinstance(event, str) else f"data: {json.dumps(event)}"
                        self.wfile.write((line + "\n\n").encode())
                        self.wfile.flush()
                        if owner.event_delay:
                            time.sleep(owner.event_delay)
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                self.close_connection = True

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._server.shutdown()
        self._server.server_close()
