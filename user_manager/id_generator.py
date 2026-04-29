import secrets

from .exceptions import UserManagerError

PREFIX_LEN    = 2
NUMBER_DIGITS = 5
NUMBER_BOUND  = 10 ** NUMBER_DIGITS
MAX_ATTEMPTS  = 20


def make_prefix(name: str) -> str:
    """Return the first PREFIX_LEN ASCII letters of name, uppercased."""
    letters = [ch for ch in name if ch.isascii() and ch.isalpha()][:PREFIX_LEN]
    if len(letters) < PREFIX_LEN:
        raise ValueError(
            f"'name' must contain at least {PREFIX_LEN} ASCII letters "
            f"to build a user_id (got '{name}')."
        )
    return "".join(letters).upper()


def claim_unique_id(prefix: str, id_set_contains, id_set_add) -> str:
    """
    Generate <prefix><zero-padded number> IDs until one is not already taken.

    id_set_contains(candidate) -> bool
    id_set_add(candidate)      -> None  (called once on success)
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        number    = secrets.randbelow(NUMBER_BOUND)
        candidate = f"{prefix}{number:0{NUMBER_DIGITS}d}"
        if not id_set_contains(candidate):
            id_set_add(candidate)
            return candidate

    raise UserManagerError(
        f"Could not generate a unique user_id for prefix '{prefix}' "
        f"after {MAX_ATTEMPTS} attempts."
    )
