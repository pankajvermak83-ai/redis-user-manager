"""Answering with Google Gemini, a model on this PC (Ollama), or any other
service that offers the widely used "OpenAI-compatible" chat API.

    Gemini:  https://generativelanguage.googleapis.com/v1beta/openai  (your Gemini API key)
    Ollama:  http://localhost:11434/v1                                 (no key, runs on your PC)
    Other:   the address, key and model you type in Settings

Only Python's own `urllib` is used, so nothing extra has to be installed.
"""

from __future__ import annotations

import json
import logging
import socket
import urllib.error
import urllib.request
from typing import Callable

from .claude_client import AskError, AskResult, Conversation
from .costs import priced
from .prompts import SYSTEM_PROMPT

log = logging.getLogger(__name__)

PDF_NOT_SUPPORTED = (
    "This AI service cannot read PDF files through Sidekick. Copy the text you need "
    "from the PDF (Ctrl+C) and ask again, or choose Claude in Settings."
)


def to_chat_content(content: object) -> object:
    """Turn the message Sidekick builds (Claude's format) into the
    OpenAI-compatible format: plain text, or a list of text and picture parts."""
    if isinstance(content, str):
        return content
    parts: list[dict] = []
    has_picture = False
    for block in content if isinstance(content, list) else []:
        kind = block.get("type") if isinstance(block, dict) else None
        if kind == "text":
            parts.append({"type": "text", "text": block["text"]})
        elif kind == "image":
            source = block["source"]
            url = f"data:{source['media_type']};base64,{source['data']}"
            parts.append({"type": "image_url", "image_url": {"url": url}})
            has_picture = True
        elif kind == "document":
            raise AskError(PDF_NOT_SUPPORTED)
    if not has_picture:
        return "\n\n".join(part["text"] for part in parts)
    return parts


def _error_message(body: bytes) -> str:
    """The human-readable part of an error reply (several shapes exist)."""
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return body.decode("utf-8", "replace").strip()[:300]
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        err = data.get("error", data)
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"]
        if isinstance(err, str):
            return err
    return str(data)[:300]


class CompatClient:
    """kind: "gemini", "ollama" or "custom"."""

    def __init__(self, settings, kind: str, api_key: str | None = None, *, timeout: float = 120.0):
        self._settings = settings
        self.kind = kind
        self._key = (api_key or "").strip() or None
        self._timeout = timeout

    # --- what this client talks to

    @property
    def model(self) -> str:
        s = self._settings
        return {"gemini": s.gemini_model, "ollama": s.ollama_model}.get(self.kind, s.custom_model)

    @property
    def base_url(self) -> str:
        s = self._settings
        return {"gemini": s.gemini_base_url, "ollama": s.ollama_url}.get(self.kind, s.custom_url).rstrip("/")

    @property
    def service_name(self) -> str:
        if self.kind == "custom":
            return self._settings.custom_name or "the AI service"
        return {"gemini": "Gemini", "ollama": "Ollama"}[self.kind]

    def has_credentials(self) -> bool:
        return self.kind == "ollama" or bool(self._key) or self.kind == "custom"

    def count_input_tokens(self, conversation: Conversation, user_content: object) -> int | None:
        return None  # not offered by these services

    # --- asking

    def _open(self, body: dict):
        if not self.base_url.startswith(("http://", "https://")):
            raise AskError("The AI service's address is missing. Add it in Settings.")
        if not self.model:
            raise AskError("The AI model's name is missing. Add it in Settings.")
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self._key and self.kind != "ollama":
            headers["Authorization"] = f"Bearer {self._key}"
        request = urllib.request.Request(
            self.base_url + "/chat/completions", data=json.dumps(body).encode("utf-8"),
            headers=headers, method="POST",
        )
        # Ollama runs on this PC, so never send it through a proxy.
        handlers = [urllib.request.ProxyHandler({})] if self.kind == "ollama" else []
        opener = urllib.request.build_opener(*handlers)
        return opener.open(request, timeout=self._timeout)

    def ask(
        self,
        conversation: Conversation,
        user_content: object,
        on_text: Callable[[str], None],
        should_stop: Callable[[], bool] = lambda: False,
    ) -> AskResult:
        message = {"role": "user", "content": to_chat_content(user_content)}
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conversation.messages + [message]
        body = {"model": self.model, "messages": messages, "stream": True}
        try:
            response = self._open(body)
        except urllib.error.HTTPError as e:
            raise self._http_error(e.code, e.read()) from e
        except (urllib.error.URLError, OSError) as e:
            raise self._connection_error(e) from e

        pieces: list[str] = []
        finish = None
        usage = None
        try:
            with response:
                for raw in response:
                    if should_stop():
                        return AskResult(cancelled=True)
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue
                    if not isinstance(chunk, dict):
                        continue
                    if chunk.get("error"):
                        raise AskError(f"{self.service_name} reported a problem: {_error_message(data.encode())}")
                    usage = chunk.get("usage") or usage
                    for choice in chunk.get("choices") or []:
                        piece = (choice.get("delta") or {}).get("content")
                        if isinstance(piece, str) and piece:
                            pieces.append(piece)
                            on_text(piece)
                        if choice.get("finish_reason"):
                            finish = choice["finish_reason"]
        except AskError:
            raise
        except (OSError, socket.timeout) as e:
            raise AskError(f"The connection to {self.service_name} was lost or took too long. Try again.") from e

        text = "".join(pieces)
        result = AskResult(text=text, stop_reason=finish, model=self.model, cost_usd=self._cost(messages, text, usage))
        if finish == "content_filter":
            result.refused = True
            result.notice = f"{self.service_name} declined to answer this. Try wording it differently."
            return result
        if finish == "length":
            result.notice = "The answer was cut off because it reached the length limit. Type \"continue\" to get the rest."
        elif not text.strip():
            result.notice = f"{self.service_name} sent back an empty answer. Try asking again."
        conversation.messages.append(message)
        conversation.messages.append({"role": "assistant", "content": text})
        return result

    def _cost(self, messages: list, answer: str, usage) -> float | None:
        """Only when you entered prices for this service in Settings."""
        rates = self._settings.prices.get(self.kind)
        if not rates:
            return None
        if isinstance(usage, dict) and "prompt_tokens" in usage:
            return priced(int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0), rates)
        # The service did not say; about 4 characters make one token.
        sent = len(json.dumps(messages)) // 4
        return priced(sent, len(answer) // 4, rates)

    # --- errors, in plain words

    def _http_error(self, status: int, body: bytes) -> AskError:
        name, model, said = self.service_name, self.model, _error_message(body)
        if status in (401, 403):
            if self.kind == "ollama":
                return AskError(f"Ollama refused the request: {said}")
            return AskError(f"Your {name} API key was not accepted. Open Settings and paste it again.", needs_key=True)
        if status == 404:
            if self.kind == "ollama":
                return AskError(
                    f"The model \"{model}\" is not installed in Ollama. Open a terminal and run:\n"
                    f"ollama pull {model}\nor pick another model in Settings."
                )
            return AskError(f"{name} has no model called \"{model}\". Check the model name in Settings.")
        if status == 429:
            if self.kind == "gemini":
                return AskError(
                    "Gemini's free limit is used up for now. The free tier allows only a few questions "
                    "a minute and a set number a day (it resets at midnight, US Pacific time). Wait a "
                    "little, or pick another model or AI service in Settings."
                )
            return AskError(f"{name} says there are too many requests right now. Wait a minute and try again.")
        if status >= 500:
            return AskError(f"{name} is having problems right now. Try again in a little while.")
        return AskError(f"{name} could not accept this request. It said: {said}")

    def _connection_error(self, error: Exception) -> AskError:
        reason = getattr(error, "reason", error)
        if self.kind == "ollama" and isinstance(reason, ConnectionRefusedError):
            return AskError(
                "Ollama is not running on this PC. Start the Ollama app (download it from "
                "ollama.com if needed), then try again."
            )
        if isinstance(reason, (socket.timeout, TimeoutError)) or isinstance(error, (socket.timeout, TimeoutError)):
            return AskError(f"{self.service_name} took too long to answer. Try again.")
        if self.kind == "ollama":
            return AskError(f"Sidekick cannot reach Ollama at {self.base_url}. Is Ollama running?")
        return AskError(f"Sidekick cannot reach {self.service_name}. Check your internet connection and try again.")
