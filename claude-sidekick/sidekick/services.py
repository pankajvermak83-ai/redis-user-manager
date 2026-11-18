"""The AI services Sidekick can use for answers shown in its own window."""

from __future__ import annotations

from . import keystore
from .claude_client import ClaudeClient
from .claude_code_client import ClaudeCodeClient
from .compat_client import CompatClient
from .config import MODELS, PROVIDER_NAMES

KEY_ACCOUNTS = {"claude": keystore.ACCOUNT, "gemini": keystore.GEMINI_ACCOUNT, "custom": keystore.CUSTOM_ACCOUNT}


def load_key(provider: str) -> str | None:
    account = KEY_ACCOUNTS.get(provider)
    key = keystore.load_api_key(account) if account else None
    if not key and provider == "gemini":
        key = keystore.env_gemini_key()
    return key


def has_key(settings) -> bool:
    """True if the chosen service has what it needs to be asked."""
    p = settings.provider
    if p == "claude":
        return bool(load_key("claude")) or keystore.env_has_credentials()
    if p == "gemini":
        return bool(load_key("gemini"))
    return True  # Claude Code, Ollama: no key; other services: a key is optional


def counts_spending(settings) -> bool:
    """True if answers from the chosen service cost money that Sidekick adds
    up: the Claude API, or a service you entered prices for in Settings."""
    return settings.provider == "claude" or bool(settings.prices.get(settings.provider))


def reads_pictures(settings) -> bool:
    """False when answers come from Claude Code, which reads text only here."""
    return settings.send_to != "api" or settings.provider != "claude_code"


def model_name(settings) -> str:
    p = settings.provider
    return {
        "claude": settings.model, "claude_code": settings.claude_code_model or "default model",
        "gemini": settings.gemini_model, "ollama": settings.ollama_model,
    }.get(p, settings.custom_model)


def service_name(settings) -> str:
    if settings.provider == "custom" and settings.custom_name:
        return settings.custom_name
    return PROVIDER_NAMES.get(settings.provider, "AI")


def short_label(settings, model: str = "") -> str:
    """For the status line, e.g. "Gemini · gemini-3.5-flash-lite"."""
    p = settings.provider
    if p == "claude":
        info = MODELS.get(model or settings.model)
        return info.short if info else (model or settings.model)
    if p == "claude_code":
        return "Claude Code (your Claude plan)"
    name = "Gemini" if p == "gemini" else service_name(settings)
    return f"{name} · {model or model_name(settings)}"


def describe(settings) -> str:
    """One line for the main window."""
    p = settings.provider
    if p == "claude_code":
        return "Claude Code on this PC, with your Claude plan (no API key, no extra bill)"
    if p == "claude":
        return f"the Claude API ({settings.model}, pay per use)"
    if p == "gemini":
        return f"Google Gemini ({settings.gemini_model})"
    if p == "ollama":
        return f"Ollama on this PC ({settings.ollama_model}, free and private)"
    return f"{service_name(settings)} ({settings.custom_model or 'no model set'})"


def make_client(settings, *, claude_kwargs: dict | None = None, claude_code_command: list[str] | None = None):
    p = settings.provider
    if p == "claude":
        return ClaudeClient(settings, api_key=load_key("claude"), **(claude_kwargs or {}))
    if p == "claude_code":
        return ClaudeCodeClient(settings, command=claude_code_command)
    return CompatClient(settings, p, api_key=load_key(p))
