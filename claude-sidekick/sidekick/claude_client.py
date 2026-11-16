"""Talking to Claude through Anthropic's official Python library.

Everything that touches the internet is in this file. It:
  * sends the question and streams the answer back piece by piece,
  * asks the API to retry on a backup model if a safety filter wrongly
    declines a harmless request (Anthropic calls this "fallbacks"),
  * turns every kind of failure into one plain-English sentence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

import anthropic

from .config import MODELS, Settings
from .costs import estimate_cost
from .prompts import SYSTEM_PROMPT

log = logging.getLogger(__name__)

# Opt-in header for the server-side backup-model feature.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AskError(Exception):
    """Something went wrong; the message is ready to show to the user."""

    def __init__(self, message: str, *, needs_key: bool = False):
        super().__init__(message)
        self.needs_key = needs_key


@dataclass
class AskResult:
    text: str = ""
    stop_reason: str | None = None
    model: str = ""  # the model that actually wrote the answer
    cost_usd: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    notice: str = ""  # an extra line to show under the answer
    refused: bool = False
    cancelled: bool = False


class Conversation:
    """The messages of one popup session (first question plus follow-ups).

    The list only ever grows. Claude's replies are stored exactly as they
    arrived, including its hidden "thinking" blocks, because the API needs
    them back unchanged on the next turn."""

    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.has_attachment = False

    @property
    def started(self) -> bool:
        return bool(self.messages)


def blocks_for_history(content: list) -> list:
    """Claude's reply, as it must be sent back on the next turn.

    Normally that is the reply unchanged. If a backup model took over part
    way through, the API marks the switch with a `fallback` block, and its
    rule is: before the last such marker keep only text (and the markers);
    keep everything from the last marker onwards as it is."""
    last = -1
    for i, block in enumerate(content):
        if getattr(block, "type", None) == "fallback":
            last = i
    if last < 0:
        return list(content)
    kept = [b for b in content[:last] if getattr(b, "type", None) in ("text", "fallback")]
    return kept + list(content[last:])


def _api_message(e: Exception) -> str:
    """The human-readable part of an API error."""
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"]
    return str(getattr(e, "message", "") or e)


_NO_KEY = "Sidekick has no API key to use. Open Settings and paste your Anthropic API key."
_NO_CREDIT = (
    "Your Anthropic account has no credit left. Add credit in the Anthropic "
    "Console (Billing), then try again."
)


def friendly_error(e: Exception, model: str) -> AskError:
    """Translate a library error into a sentence a beginner can act on.
    The most specific kinds are checked first."""
    if isinstance(e, anthropic.AuthenticationError):
        return AskError(
            "Your API key was not accepted. Open Settings and paste the key again.",
            needs_key=True,
        )
    if isinstance(e, anthropic.PermissionDeniedError):
        return AskError(f"Your API key is not allowed to do this. Anthropic said: {_api_message(e)}")
    if isinstance(e, anthropic.NotFoundError):
        return AskError(
            f"Your account cannot use the model '{model}'. Pick a different model in Settings."
        )
    if isinstance(e, anthropic.RequestTooLargeError):
        return AskError("That is too much to send at once. Remove the attachment or copy a smaller part.")
    if isinstance(e, anthropic.RateLimitError):
        return AskError("Too many requests right now. Wait a minute, then try again.")
    if isinstance(e, anthropic.BadRequestError):
        message = _api_message(e)
        if "credit balance" in message.lower():
            return AskError(_NO_CREDIT)
        return AskError(f"Claude could not accept this request. Anthropic said: {message}")
    if isinstance(e, anthropic.APIStatusError):
        if e.status_code == 402 or getattr(e, "type", None) == "billing_error":
            return AskError(_NO_CREDIT)
        if e.status_code >= 500:
            return AskError("Claude's servers are busy at the moment. Try again in a little while.")
        return AskError(f"Claude returned an error ({e.status_code}). Anthropic said: {_api_message(e)}")
    if isinstance(e, anthropic.APITimeoutError):
        return AskError("Claude took too long to answer. Check your internet connection and try again.")
    if isinstance(e, anthropic.APIConnectionError):
        return AskError("Sidekick cannot reach Claude. Check your internet connection and try again.")
    if isinstance(e, getattr(anthropic, "CredentialsError", ())):
        return AskError(_NO_KEY, needs_key=True)
    return AskError(f"Something unexpected went wrong while talking to Claude ({type(e).__name__}).")


class ClaudeClient:
    def __init__(
        self,
        settings: Settings,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        max_retries: int = 1,
    ):
        self._settings = settings
        kwargs: dict = {
            # Give up connecting after 10 s (so "no internet" is reported
            # quickly) but allow long pauses while Claude is thinking.
            "timeout": anthropic.Timeout(120.0, connect=10.0),
            "max_retries": max_retries,
        }
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        # With no key given, the library looks for ANTHROPIC_API_KEY itself.
        self._client = anthropic.Anthropic(**kwargs)
        self._fallbacks_ok = True

    def has_credentials(self) -> bool:
        """True if a key (or token) is available to send with requests."""
        return bool(getattr(self._client, "api_key", None) or getattr(self._client, "auth_token", None))

    # ----------------------------------------------------------------- request

    def _request_args(self, messages: list, cache: bool) -> dict:
        model = self._settings.model
        args: dict = {
            "model": model,
            "max_tokens": self._settings.max_output_tokens,
            "system": SYSTEM_PROMPT,
            "messages": messages,
            # Claude decides for itself how much to think; "effort" nudges it.
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self._settings.effort},
        }
        if cache:
            # Follow-up questions re-send the same beginning; caching makes
            # that repeated part much cheaper.
            args["cache_control"] = {"type": "ephemeral"}
        if MODELS[model].fallbacks and self._fallbacks_ok:
            args["betas"] = [FALLBACK_BETA]
            args["fallbacks"] = "default"
        return args

    def _stream(self, messages: list, cache: bool, on_text: Callable[[str], None], should_stop: Callable[[], bool]):
        """Run one request. Returns the finished message, or None if stopped."""
        with self._client.beta.messages.stream(**self._request_args(messages, cache)) as stream:
            for event in stream:
                if should_stop():
                    return None  # leaving the `with` block closes the connection
                if event.type == "text":
                    on_text(event.text)
            return stream.get_final_message()

    def ask(
        self,
        conversation: Conversation,
        user_content: object,
        on_text: Callable[[str], None],
        should_stop: Callable[[], bool] = lambda: False,
    ) -> AskResult:
        """Send `user_content` as the next user turn and stream the reply.

        `on_text` is called with each new piece of the answer.
        Raises AskError (with a ready-to-show message) if the request fails."""
        model = self._settings.model
        user_message = {"role": "user", "content": user_content}
        messages = conversation.messages + [user_message]
        cache = conversation.started or _has_media(user_content)

        final = None
        for attempt in (1, 2):
            try:
                final = self._stream(messages, cache, on_text, should_stop)
                break
            except anthropic.BadRequestError as e:
                # Some accounts may not have the backup-model feature. If the
                # API says so, switch it off for this session and try once more.
                if attempt == 1 and self._fallbacks_ok and MODELS[model].fallbacks and "anthropic-beta" in _api_message(e).lower():
                    log.warning("Backup-model feature was rejected; continuing without it.")
                    self._fallbacks_ok = False
                    continue
                raise friendly_error(e, model) from e
            except anthropic.AnthropicError as e:
                log.warning("Request failed: %s", type(e).__name__)
                raise friendly_error(e, model) from e
            except TypeError as e:
                # The library raises a plain TypeError when it has no key at all.
                if self.has_credentials():
                    raise
                raise AskError(_NO_KEY, needs_key=True) from e

        if final is None:
            return AskResult(cancelled=True)

        result = AskResult(
            text="".join(b.text for b in final.content if b.type == "text"),
            stop_reason=final.stop_reason,
            model=final.model,
            cost_usd=estimate_cost(final.model, final.usage),
            input_tokens=int(getattr(final.usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(final.usage, "output_tokens", 0) or 0),
        )

        # Always look at stop_reason before trusting the content.
        if final.stop_reason == "refusal":
            result.refused = True
            result.notice = (
                "Claude declined to answer this. Try wording the question differently, "
                "or ask about a smaller part."
            )
            return result  # a declined turn is not added to the conversation

        notes = []
        if final.stop_reason == "max_tokens":
            if result.text.strip():
                notes.append("The answer was cut off because it reached the length limit. Type \"continue\" to get the rest.")
            else:
                notes.append("Claude ran out of room before answering. Try again, or choose a lower thinking effort in Settings.")
        elif not result.text.strip():
            notes.append("Claude sent back an empty answer. Try asking again.")
        if final.model and final.model != model:
            notes.append(f"Answered by a backup model ({final.model}) because the first one declined.")
        result.notice = " ".join(notes)

        conversation.messages.append(user_message)
        conversation.messages.append({"role": "assistant", "content": blocks_for_history(final.content)})
        if _has_media(user_content):
            conversation.has_attachment = True
        return result

    # ------------------------------------------------------------ token count

    def count_input_tokens(self, conversation: Conversation, user_content: object) -> int | None:
        """How many tokens this request would send (a free API call).
        Returns None if the count could not be obtained."""
        messages = conversation.messages + [{"role": "user", "content": user_content}]
        try:
            counted = self._client.messages.count_tokens(
                model=self._settings.model, system=SYSTEM_PROMPT, messages=messages
            )
            return int(counted.input_tokens)
        except (anthropic.AnthropicError, TypeError) as e:
            log.warning("Token count failed: %s", type(e).__name__)
            return None


def _has_media(user_content: object) -> bool:
    if not isinstance(user_content, list):
        return False
    return any(isinstance(b, dict) and b.get("type") in ("image", "document") for b in user_content)
