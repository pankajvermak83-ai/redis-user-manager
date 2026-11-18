"""Where API keys are kept (Anthropic's and Google's).

On Windows the keys go into Windows Credential Manager (through the
`keyring` library), not into a text file. If you prefer, you can instead set
the ANTHROPIC_API_KEY or GEMINI_API_KEY environment variable.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

SERVICE = "Sidekick"
ACCOUNT = "anthropic-api-key"
GEMINI_ACCOUNT = "gemini-api-key"
CUSTOM_ACCOUNT = "custom-service-api-key"


class KeyStoreError(Exception):
    """A problem saving the key, written so it can be shown to the user."""


def _keyring():
    try:
        import keyring

        return keyring
    except Exception:  # not installed, or no usable backend
        return None


def load_api_key(account: str = ACCOUNT) -> str | None:
    kr = _keyring()
    if kr is None:
        return None
    try:
        key = kr.get_password(SERVICE, account)
    except Exception as e:
        log.warning("Could not read the saved API key: %s", type(e).__name__)
        return None
    return key or None


def save_api_key(key: str, account: str = ACCOUNT) -> None:
    key = (key or "").strip()
    if not key:
        raise KeyStoreError("The API key is empty.")
    kr = _keyring()
    if kr is None:
        raise KeyStoreError(
            "The 'keyring' library is missing, so the key cannot be saved safely. "
            "Run 1-Setup.bat again."
        )
    try:
        kr.set_password(SERVICE, account, key)
    except Exception as e:
        raise KeyStoreError(f"Windows would not save the key ({type(e).__name__}).") from e


def delete_api_key(account: str = ACCOUNT) -> None:
    kr = _keyring()
    if kr is None:
        return
    try:
        kr.delete_password(SERVICE, account)
    except Exception:
        pass  # nothing was saved


def env_has_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def looks_like_anthropic_key(key: str) -> bool:
    return (key or "").strip().startswith("sk-ant-")


def env_gemini_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or None


def looks_like_gemini_key(key: str) -> bool:
    return (key or "").strip().startswith("AIza")  # Google API keys start like this
