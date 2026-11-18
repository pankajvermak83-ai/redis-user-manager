"""Settings: what they are, their defaults, and loading/saving them.

Settings live in one small JSON file:
    Windows:  %APPDATA%\\Sidekick\\config.json
    Others:   ~/.config/Sidekick/config.json   (only used for development)

API keys are NOT stored here. See keystore.py.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "Sidekick"

# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelInfo:
    label: str  # shown in Settings
    short: str  # shown in the status line
    fallbacks: bool  # does the API offer a backup model if this one declines?


# The models you can pick in Settings. Opus 5.5 is the default.
MODELS: dict[str, ModelInfo] = {
    "claude-opus-5-5": ModelInfo("Claude Opus 5.5 - smartest (default)", "Opus 5.5", True),
    "claude-sonnet-5-5": ModelInfo("Claude Sonnet 5.5 - faster, about half the price", "Sonnet 5.5", True),
    # Anthropic's docs: Haiku 5.5 has no server-side fallback, so none is requested.
    "claude-haiku-5-5": ModelInfo("Claude Haiku 5.5 - fastest and cheapest", "Haiku 5.5", False),
}
DEFAULT_MODEL = "claude-opus-5-5"

# How hard Claude thinks before answering. Lower = faster and cheaper.
EFFORTS = ("low", "medium", "high")
DEFAULT_EFFORT = "medium"

# Where a question goes when you click the button in the Ask window.
#   claude_app: the Claude desktop app opens with the question filled in.
#   chrome:     the Claude website (claude.ai) opens in Chrome.
#   api:        Sidekick asks Claude itself and shows the answer (API key).
# The first two use your normal Claude plan, so there is no extra bill.
SEND_TO_CHOICES = ("claude_app", "chrome", "api")
DEFAULT_SEND_TO = "claude_app"

# Which AI answers when the answer is shown inside Sidekick ("api" above).
#   claude: Anthropic's Claude API (an API key, pay per use)
#   gemini: Google's Gemini API (an API key; has a limited free tier)
#   ollama: a model running on this PC with Ollama (free, private, offline)
#   custom: any other service with an "OpenAI-compatible" chat API (OpenAI,
#           DeepSeek, Groq, Mistral, OpenRouter, LM Studio, ...). You type in
#           its address, key and model, so new services need no code change.
#   claude_code: Claude Code, Anthropic's own command-line tool, signed in
#           with your Claude plan: no API key and no separate bill.
PROVIDERS = ("claude_code", "claude", "gemini", "ollama", "custom")
DEFAULT_PROVIDER = "claude_code"
PROVIDER_NAMES = {
    "claude_code": "Claude Code", "claude": "Claude API", "gemini": "Google Gemini",
    "ollama": "Ollama", "custom": "Other service",
}
CLAUDE_CODE_MODELS = ("", "haiku", "sonnet", "opus")  # "" = Claude Code's own choice
CLAUDE_MODEL_IDS = tuple(MODELS)

# Gemini and Ollama are reached through their "OpenAI-compatible" chat API.
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_MODELS = ("gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.1-flash-lite")
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"  # the free tier allows the most questions a day with it
OLLAMA_URL = "http://localhost:11434/v1"
OLLAMA_MODELS = ("gemma4:e4b", "gemma4:e2b", "qwen3.5")
DEFAULT_OLLAMA_MODEL = "gemma4:e4b"

# What the hotkey asks when you have selected something ("instant" mode).
SMART_PROMPT = (
    "Help me with this. If it is a question, answer it. If it is an error message, explain what it "
    "means and how to fix it. If it is not in English, translate it into English. Otherwise, explain "
    "it simply and point out anything I should do."
)
HOTKEY_ACTIONS: dict[str, tuple[str, str]] = {  # key: (label in Settings, what is asked)
    "smart": ("Help with this (Sidekick decides)", SMART_PROMPT),
    "explain": ("Explain", "Explain this in simple words."),
    "fix": ("Fix", "Find what is wrong here and give me the corrected version."),
    "summarize": ("Summarize", "Summarize this in a few short points."),
    "improve": ("Improve writing", "Rewrite this so it is clear, correct and polite. Keep my meaning."),
    "reply": ("Draft reply", "Write a short, polite reply to this."),
    "open": ("Nothing: only open the window", ""),
}
DEFAULT_HOTKEY_ACTION = "smart"

# --------------------------------------------------------------------------
# Defaults
# --------------------------------------------------------------------------

DEFAULT_HOTKEY = "ctrl+shift+space"
# Tried automatically when the chosen hotkey is already used by another app.
FALLBACK_HOTKEY = "ctrl+alt+shift+space"

# If one of these words appears in the name or title of the window you were
# in, Sidekick does not read your clipboard and does not send the title.
DEFAULT_PRIVATE_WORDS = [
    # password managers
    "keepass", "1password", "bitwarden", "lastpass", "dashlane", "nordpass",
    "roboform", "enpass", "proton pass", "keeper",
    # private browsing
    "inprivate", "incognito", "private browsing", "private window",
    # money
    "bank", "netbanking", "paypal", "wallet",
    # sign-in screens
    "password", "sign in", "log in", "login", "windows security",
]

DEFAULT_QUICK_ACTIONS = [
    {"label": "Explain", "prompt": "Explain this in simple words."},
    {"label": "Fix", "prompt": "Find what is wrong here and give me the corrected version."},
    {"label": "Summarize", "prompt": "Summarize this in a few short points."},
    {"label": "Improve writing", "prompt": "Rewrite this so it is clear, correct and polite. Keep my meaning."},
    {"label": "Draft reply", "prompt": "Write a short, polite reply to this."},
]


@dataclass
class Settings:
    send_to: str = DEFAULT_SEND_TO
    # One key press: copy the selected text and ask right away.
    instant: bool = True
    hotkey_action: str = DEFAULT_HOTKEY_ACTION
    # For answers inside Sidekick:
    provider: str = DEFAULT_PROVIDER
    gemini_model: str = DEFAULT_GEMINI_MODEL
    gemini_base_url: str = GEMINI_BASE_URL
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    ollama_url: str = OLLAMA_URL
    claude_code_model: str = ""  # "", "haiku", "sonnet", "opus" or a full model name
    claude_code_command: str = ""  # full path to claude.exe, if it is not found by itself
    custom_name: str = ""  # e.g. "Groq": only used in messages
    custom_url: str = ""  # e.g. https://api.groq.com/openai/v1
    custom_model: str = ""
    # Your own prices, in US dollars per million tokens: {"claude": [input, output], ...}.
    # Used for cost estimates and the daily limit. Without one, Claude uses
    # Sidekick's built-in price list and the other services count as free.
    prices: dict = field(default_factory=dict)
    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    hotkey: str = DEFAULT_HOTKEY
    # Upper limit for one answer (this also has to cover Claude's thinking).
    max_output_tokens: int = 16000
    # Sidekick stops sending once today's estimated spend passes this. 0 = no limit.
    daily_limit_usd: float = 2.00
    # Ask "send anyway?" when one request is estimated to cost more than this.
    confirm_cost_usd: float = 0.25
    # Tell Claude which app and window you were in (helps it give exact steps).
    send_window_title: bool = True
    # Only use the clipboard automatically if you copied within this many seconds.
    clipboard_fresh_seconds: int = 120
    # Longest text Sidekick will put in the box (extra text is cut, and it says so).
    max_text_chars: int = 30000
    # Pictures are shrunk so the longest side is at most this many pixels.
    max_image_edge: int = 1920
    private_words: list[str] = field(default_factory=lambda: list(DEFAULT_PRIVATE_WORDS))
    quick_actions: list[dict] = field(default_factory=lambda: [dict(a) for a in DEFAULT_QUICK_ACTIONS])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object) -> "Settings":
        """Build Settings from loaded JSON. Anything missing or invalid
        quietly falls back to its default, so a damaged file never stops
        Sidekick from starting."""
        s = cls()
        if not isinstance(data, dict):
            return s

        send_to = data.get("send_to")
        if isinstance(send_to, str) and send_to in SEND_TO_CHOICES:
            s.send_to = send_to
        if isinstance(data.get("instant"), bool):
            s.instant = data["instant"]
        action = data.get("hotkey_action")
        if isinstance(action, str) and action in HOTKEY_ACTIONS:
            s.hotkey_action = action
        provider = data.get("provider")
        if isinstance(provider, str) and provider in PROVIDERS:
            s.provider = provider
        code_model = data.get("claude_code_model")
        if isinstance(code_model, str) and len(code_model) < 100:
            s.claude_code_model = code_model.strip()
        command = data.get("claude_code_command")
        if isinstance(command, str) and len(command) < 400:
            s.claude_code_command = command.strip()
        for name in ("gemini_model", "ollama_model", "custom_model", "custom_name"):
            value = data.get(name)
            if isinstance(value, str) and value.strip() and len(value) < 200:
                setattr(s, name, value.strip())
        for name in ("gemini_base_url", "ollama_url", "custom_url"):
            value = data.get(name)
            if isinstance(value, str) and value.strip().startswith(("http://", "https://")):
                setattr(s, name, value.strip().rstrip("/"))
        prices = data.get("prices")
        if isinstance(prices, dict):
            for key, pair in prices.items():
                if key in PROVIDERS and valid_price_pair(pair):
                    s.prices[key] = [float(pair[0]), float(pair[1])]

        model = data.get("model")
        if isinstance(model, str) and model.strip().startswith("claude-") and len(model) < 100:
            s.model = model.strip()  # new Claude models can be typed in

        effort = data.get("effort")
        if isinstance(effort, str) and effort in EFFORTS:
            s.effort = effort

        hotkey = data.get("hotkey")
        if isinstance(hotkey, str) and hotkey.strip():
            s.hotkey = hotkey.strip().lower()

        s.max_output_tokens = _as_int(data.get("max_output_tokens"), s.max_output_tokens, 1000, 64000)
        s.daily_limit_usd = _as_float(data.get("daily_limit_usd"), s.daily_limit_usd, 0.0, 1000.0)
        s.confirm_cost_usd = _as_float(data.get("confirm_cost_usd"), s.confirm_cost_usd, 0.0, 1000.0)
        s.clipboard_fresh_seconds = _as_int(data.get("clipboard_fresh_seconds"), s.clipboard_fresh_seconds, 5, 3600)
        s.max_text_chars = _as_int(data.get("max_text_chars"), s.max_text_chars, 1000, 400000)
        s.max_image_edge = _as_int(data.get("max_image_edge"), s.max_image_edge, 640, 2576)

        if isinstance(data.get("send_window_title"), bool):
            s.send_window_title = data["send_window_title"]

        words = data.get("private_words")
        if isinstance(words, list):
            s.private_words = [w.strip().lower() for w in words if isinstance(w, str) and w.strip()]

        actions = data.get("quick_actions")
        if isinstance(actions, list):
            cleaned = []
            for a in actions:
                if (
                    isinstance(a, dict)
                    and isinstance(a.get("label"), str)
                    and isinstance(a.get("prompt"), str)
                    and a["label"].strip()
                    and a["prompt"].strip()
                ):
                    cleaned.append({"label": a["label"].strip(), "prompt": a["prompt"].strip()})
            if cleaned:
                s.quick_actions = cleaned[:8]
        return s


def valid_price_pair(pair: object) -> bool:
    """[input price, output price], each a number from 0 to 1000 ($ per million tokens)."""
    return (
        isinstance(pair, (list, tuple)) and len(pair) == 2
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1000 for v in pair)
    )


def _as_int(value: object, default: int, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(low, min(high, int(value)))


def _as_float(value: object, default: float, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(low, min(high, float(value)))


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------


def config_dir() -> Path:
    """The folder where Sidekick keeps its settings and log."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


def load_settings(path: Path | None = None) -> Settings:
    path = path or config_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return Settings.from_dict(json.load(f))
    except FileNotFoundError:
        return Settings()
    except (OSError, ValueError):
        # Unreadable or damaged file: start with defaults instead of crashing.
        return Settings()


def save_settings(settings: Settings, path: Path | None = None) -> None:
    path = path or config_path()
    write_json_atomic(path, settings.to_dict())


def write_json_atomic(path: Path, data: object) -> None:
    """Write JSON so that a crash half-way never leaves a broken file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
