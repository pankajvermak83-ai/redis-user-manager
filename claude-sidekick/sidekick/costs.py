"""Rough cost of each answer, and a running total for today.

These are ESTIMATES so you are never surprised by a bill. The real numbers
are in the Anthropic Console (Usage / Billing).
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path

from .config import write_json_atomic

log = logging.getLogger(__name__)

# US dollars per million tokens: (input, output, cached-input read).
# From Anthropic's price list as of this date. Update here if prices change.
PRICES_AS_OF = "2026-11-03"
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    # Backup models the API may switch to if the chosen model declines.
    "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 0.50),
    "claude-sonnet-5": (2.00, 10.00, 0.20),
}
# Haiku 5.5 costs more when the prompt is over 100,000 tokens.
_HAIKU_LONG_PROMPT = (0.50, 2.50, 0.05)
_CACHE_WRITE_MULTIPLIER = 1.25  # writing to the 5-minute cache costs 1.25x input


def _rates(model: str, prompt_tokens: int) -> tuple[float, float, float] | None:
    if model == "claude-haiku-5-5" and prompt_tokens > 100_000:
        return _HAIKU_LONG_PROMPT
    return PRICES.get(model)


def _one(model: str, part: object) -> float | None:
    """Cost in dollars of one usage record."""
    def n(name: str) -> int:
        return int(getattr(part, name, 0) or 0)

    inp, out = n("input_tokens"), n("output_tokens")
    cache_write, cache_read = n("cache_creation_input_tokens"), n("cache_read_input_tokens")
    rates = _rates(model, inp + cache_write + cache_read)
    if rates is None:
        return None
    in_rate, out_rate, read_rate = rates
    return (
        inp * in_rate
        + cache_write * in_rate * _CACHE_WRITE_MULTIPLIER
        + cache_read * read_rate
        + out * out_rate
    ) / 1_000_000


def estimate_cost(model: str, usage: object) -> float | None:
    """Estimated dollars for one reply. Returns None if the price is unknown.

    When a backup model stepped in, the API lists every attempt under
    `usage.iterations`; each attempt is priced with its own model.
    """
    if usage is None:
        return None
    iterations = getattr(usage, "iterations", None)
    if iterations:
        total = 0.0
        for part in iterations:
            cost = _one(getattr(part, "model", None) or model, part)
            if cost is None:
                return None
            total += cost
        return total
    return _one(model, usage)


def input_cost(model: str, input_tokens: int) -> float | None:
    """Dollars to SEND this many tokens (before any answer)."""
    rates = _rates(model, input_tokens)
    if rates is None:
        return None
    return input_tokens * rates[0] / 1_000_000


def format_money(usd: float | None) -> str:
    if usd is None:
        return "cost unknown"
    if usd < 0.0005:
        return "under 0.1¢"
    if usd < 0.995:
        cents = usd * 100
        return f"{cents:.1f}¢" if cents < 10 else f"{cents:.0f}¢"
    return f"${usd:.2f}"


class DailySpend:
    """Adds up today's estimated spending in a small file. No questions or
    answers are stored: only the date, a dollar total and a count."""

    def __init__(self, path: Path):
        self._path = path

    def _read(self) -> dict:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
        return {}

    @staticmethod
    def _today() -> str:
        return datetime.date.today().isoformat()

    def today_total(self) -> float:
        data = self._read()
        if data.get("date") != self._today():
            return 0.0
        try:
            return max(0.0, float(data.get("usd", 0.0)))
        except (TypeError, ValueError):
            return 0.0

    def add(self, usd: float | None) -> float:
        """Record one reply and return the new total for today."""
        total = self.today_total() + max(0.0, usd or 0.0)
        data = self._read()
        count = int(data.get("requests", 0) or 0) if data.get("date") == self._today() else 0
        try:
            write_json_atomic(self._path, {"date": self._today(), "usd": round(total, 6), "requests": count + 1})
        except OSError as e:
            log.warning("Could not save today's spending: %s", e)
        return total
