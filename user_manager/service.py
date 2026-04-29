import logging
from typing import Any, Dict, List, Optional

import redis
from redis.exceptions import ConnectionError as RedisConnectionError

from . import id_generator, repository
from .config import build_redis_client
from .exceptions import UserAlreadyExistsException, UserManagerError

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

UserData = Dict[str, str]

_RESERVED = frozenset({"user_id", "name"})


class UserManager:
    def __init__(self, *, client: Optional[redis.Redis] = None) -> None:
        self._client = client or build_redis_client()
        try:
            self._client.ping()
        except RedisConnectionError as exc:
            raise ConnectionError(f"Unable to reach Redis: {exc}") from exc
        logger.info("UserManager ready.")

    # -------------------------------------------------------------------------

    def add_user(self, name: str, **extra: Any) -> str:
        name = self._validate_name(name)
        self._check_reserved(extra)

        prefix = id_generator.make_prefix(name)

        if not repository.reserve_name(self._client, name):
            raise UserAlreadyExistsException(f"A user named '{name}' already exists.")

        user_id: Optional[str] = None
        try:
            user_id = id_generator.claim_unique_id(
                prefix,
                id_set_contains=lambda uid: repository.id_exists(self._client, uid),
                id_set_add=lambda uid: repository.add_user_id(self._client, uid),
            )
            repository.write_user(
                self._client,
                user_id,
                {"user_id": user_id, "name": name, **{k: str(v) for k, v in extra.items()}},
            )
        except Exception:
            repository.rollback(self._client, name=name, user_id=user_id)
            raise

        logger.info("User created: name='%s' user_id=%s", name, user_id)
        return user_id

    def get_user_by_id(self, user_id: str) -> UserData:
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("'user_id' must be a non-empty string.")
        return repository.read_user(self._client, user_id.strip())

    def get_all_users(self) -> List[UserData]:
        users = repository.fetch_all(self._client)
        logger.info("get_all_users -> %d user(s)", len(users))
        return users

    # -------------------------------------------------------------------------

    @staticmethod
    def _validate_name(name: str) -> str:
        if not isinstance(name, str):
            raise ValueError("'name' must be a string.")
        name = name.strip()
        if not name:
            raise ValueError("'name' must be a non-empty string.")
        return name

    @staticmethod
    def _check_reserved(fields: dict) -> None:
        bad = _RESERVED.intersection(fields)
        if bad:
            raise ValueError(f"Reserved field(s) not allowed in extra: {sorted(bad)}")
