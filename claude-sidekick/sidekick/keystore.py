"""Where the Anthropic API key is kept.

On Windows the key goes into Windows Credential Manager (through the
`keyring` library), not into a text file. If you prefer, you can instead set
the ANTHROPIC_API_KEY environment variable and Sidekick will use that.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

SERVICE = "Sidekick"
ACCOUNT = "anthropic-api-key"


class KeyStoreError(Exception):
    """A problem saving the key, written so it can be shown to the user."""


def _keyring():
    try:
        import keyring

        return keyring
    except Exception:  # not installed, or no usable backend
        return None


def load_api_key() -> str | None:
    kr = _keyring()
    if kr is None:
        return None
    try:
        key = kr.get_password(SERVICE, ACCOUNT)
    except Exception as e:
        log.warning("Could not read the saved API key: %s", type(e).__name__)
        return None
    return key or None


def save_api_key(key: str) -> None:
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
        kr.set_password(SERVICE, ACCOUNT, key)
    except Exception as e:
        raise KeyStoreError(f"Windows would not save the key ({type(e).__name__}).") from e


def delete_api_key() -> None:
    kr = _keyring()
    if kr is None:
        return
    try:
        kr.delete_password(SERVICE, ACCOUNT)
    except Exception:
        pass  # nothing was saved


def env_has_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def looks_like_anthropic_key(key: str) -> bool:
    return (key or "").strip().startswith("sk-ant-")
