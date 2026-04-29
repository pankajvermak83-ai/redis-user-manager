import os

import redis

from .exceptions import MissingEnvironmentVariableException


def build_redis_client() -> redis.Redis:
    host = _require("REDIS_HOST")
    port = _parse_int("REDIS_PORT", min_val=1, max_val=65535)
    db   = _parse_int("REDIS_DB",   min_val=0)

    return redis.Redis(
        host=host,
        port=port,
        db=db,
        password=os.getenv("REDIS_PASSWORD") or None,
        ssl=os.getenv("REDIS_SSL", "false").strip().lower() == "true",
        decode_responses=True,
        socket_timeout=_parse_float("REDIS_SOCKET_TIMEOUT", default=5.0),
        socket_connect_timeout=_parse_float("REDIS_SOCKET_CONNECT_TIMEOUT", default=5.0),
        health_check_interval=30,
        retry_on_timeout=True,
    )


def _require(var: str) -> str:
    value = os.getenv(var)
    if not value:
        raise MissingEnvironmentVariableException(
            f"Required environment variable '{var}' is not set."
        )
    return value


def _parse_int(var: str, *, min_val=None, max_val=None) -> int:
    raw = _require(var)
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"Env var '{var}' must be an integer, got '{raw}'.")
    if min_val is not None and value < min_val:
        raise ValueError(f"Env var '{var}' must be >= {min_val}, got {value}.")
    if max_val is not None and value > max_val:
        raise ValueError(f"Env var '{var}' must be <= {max_val}, got {value}.")
    return value


def _parse_float(var: str, *, default: float) -> float:
    raw = os.getenv(var)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"Env var '{var}' must be a number, got '{raw}'.")
