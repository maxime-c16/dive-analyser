"""Argon2id password authority (P5).

Modern, memory-hard password hashing via a maintained library
(argon2-cffi). Policy:
- Argon2id ONLY (no plaintext, no reversible encryption, no legacy algos)
- verification through the library's safe verifier (constant-time compare
  inside the C implementation; no Python-level hash string comparison)
- no raw password is ever logged, hashed into an identifier, or stored
- parameters are pinned here and re-hashing is flagged via check_needs_rehash
  (no silent parameter drift)
"""

from argon2 import PasswordHasher, Type
from argon2.exceptions import (
    HashingError,
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

# Pinned Argon2id parameters (OWASP-recommended baseline class):
# 64 MiB memory, 3 iterations, 2 lanes, 32-byte tag.
_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

ALGORITHM_LABEL = "argon2id"


def hash_password(raw_password: str) -> str:
    """Hash a raw password into an Argon2id PHC string."""
    return _HASHER.hash(raw_password)


def verify_password(stored_hash: str, raw_password: str) -> bool:
    """Verify a raw password against a stored Argon2id PHC string.

    Returns a single boolean for EVERY failure family (wrong password,
    malformed/stale hash, hashing error) so callers cannot distinguish
    causes and cannot build a user-existence or hash-quality oracle.
    """
    try:
        _HASHER.verify(stored_hash, raw_password)
    except VerifyMismatchError:
        return False
    except (InvalidHashError, VerificationError, HashingError, ValueError):
        return False
    return True


def password_needs_rehash(stored_hash: str) -> bool:
    """True when the stored hash no longer matches the pinned parameters."""
    try:
        return _HASHER.check_needs_rehash(stored_hash)
    except Exception:
        return False
