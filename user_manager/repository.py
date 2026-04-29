import logging
from typing import Dict, List, Optional

import redis
from redis.exceptions import RedisError

from .exceptions import UserManagerError, UserNotFoundException

logger = logging.getLogger(__name__)

UserData = Dict[str, str]

NAMES_KEY    = "app:usernames"
USER_IDS_KEY = "app:user_ids"
USER_PREFIX  = "user:"

BATCH_SIZE = 1000


def user_key(user_id: str) -> str:
    return f"{USER_PREFIX}{user_id}"


# --- name / id set helpers ---------------------------------------------------

def reserve_name(client: redis.Redis, name: str) -> bool:
    """Add name to the names set. Returns False if it already existed."""
    try:
        return client.sadd(NAMES_KEY, name) == 1
    except RedisError as exc:
        raise UserManagerError(f"Failed to reserve name '{name}': {exc}") from exc


def id_exists(client: redis.Redis, user_id: str) -> bool:
    return client.sismember(USER_IDS_KEY, user_id)


def add_user_id(client: redis.Redis, user_id: str) -> None:
    client.sadd(USER_IDS_KEY, user_id)


# --- user hash ----------------------------------------------------------------

def write_user(client: redis.Redis, user_id: str, data: UserData) -> None:
    client.hset(user_key(user_id), mapping=data)


def read_user(client: redis.Redis, user_id: str) -> UserData:
    try:
        data = client.hgetall(user_key(user_id))
    except RedisError as exc:
        raise UserManagerError(f"Failed to fetch user '{user_id}': {exc}") from exc
    if not data:
        raise UserNotFoundException(f"No user found with ID '{user_id}'.")
    return data


# --- bulk read ----------------------------------------------------------------

def fetch_all(client: redis.Redis) -> List[UserData]:
    try:
        seen:  set      = set()
        users: List     = []
        batch: List[str] = []

        for uid in client.sscan_iter(USER_IDS_KEY, count=BATCH_SIZE):
            batch.append(uid)
            if len(batch) >= BATCH_SIZE:
                _fetch_batch(client, batch, seen, users)
                batch.clear()

        if batch:
            _fetch_batch(client, batch, seen, users)

    except RedisError as exc:
        raise UserManagerError(f"Failed to list users: {exc}") from exc

    return users


def _fetch_batch(client, ids, seen, out):
    pipe = client.pipeline()
    for uid in ids:
        pipe.hgetall(user_key(uid))
    for record in pipe.execute():
        if not record:
            continue
        name = record.get("name")
        if name and name not in seen:
            seen.add(name)
            out.append(record)


# --- rollback -----------------------------------------------------------------

def rollback(client: redis.Redis, *, name: str, user_id: Optional[str]) -> None:
    try:
        pipe = client.pipeline()
        pipe.srem(NAMES_KEY, name)
        if user_id:
            pipe.srem(USER_IDS_KEY, user_id)
            pipe.delete(user_key(user_id))
        pipe.execute()
    except RedisError:
        logger.exception("Rollback failed (name='%s' user_id=%s)", name, user_id)
