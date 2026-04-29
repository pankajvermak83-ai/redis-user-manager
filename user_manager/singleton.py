import logging
import os
import threading
from typing import Optional

from .exceptions import MissingEnvironmentVariableException
from .service import UserManager

logger = logging.getLogger(__name__)

_instance: Optional[UserManager] = None
_lock = threading.Lock()


def get_user_service() -> UserManager:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = UserManager()
    return _instance


def reset_user_service() -> None:
    global _instance
    with _lock:
        _instance = None


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        get_user_service()
        logger.info("UserManager service is ready.")
    except (MissingEnvironmentVariableException, ValueError, ConnectionError) as exc:
        logger.error("Startup failed: %s", exc)
        raise SystemExit(1)
