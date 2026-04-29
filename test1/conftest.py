import sys
import types
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Stub redis before any test module imports user_manager
# ---------------------------------------------------------------------------

class FakeRedisError(Exception):
    pass


class FakeConnectionError(FakeRedisError):
    pass


def install_redis_stub():
    redis_stub = types.ModuleType("redis")
    redis_stub.Redis = MagicMock
    redis_stub.RedisError = FakeRedisError
    redis_stub.ConnectionError = FakeConnectionError

    exc_stub = types.ModuleType("redis.exceptions")
    exc_stub.ConnectionError = FakeConnectionError
    exc_stub.RedisError = FakeRedisError

    sys.modules.setdefault("redis", redis_stub)
    sys.modules.setdefault("redis.exceptions", exc_stub)


install_redis_stub()
