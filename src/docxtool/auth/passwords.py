"""Argon2id password hashing. Plain passwords never leave this module."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_HASHER = PasswordHasher()


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> tuple[bool, bool]:
    try:
        valid = _HASHER.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False, False
    return bool(valid), bool(_HASHER.check_needs_rehash(password_hash))
