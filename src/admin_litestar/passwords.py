"""scrypt password hashing, independent of where the hash is stored."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from base64 import b64decode, b64encode
from binascii import Error as BinasciiError

from .constants import (
    HASH_PARTS,
    HASH_PREFIX,
    HASH_SEPARATOR,
    SALT_BYTES,
    SCRYPT_DKLEN,
    SCRYPT_N,
    SCRYPT_P,
    SCRYPT_R,
)


def _derive(raw: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    """Return the scrypt digest for a plaintext password and parameters."""
    return hashlib.scrypt(raw.encode(), salt=salt, n=n, r=r, p=p, dklen=SCRYPT_DKLEN)


def hash_password(raw: str) -> str:
    """Encode a plaintext password as ``scrypt$n$r$p$salt_b64$hash_b64``."""
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _derive(raw, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    parts = (
        HASH_PREFIX,
        str(SCRYPT_N),
        str(SCRYPT_R),
        str(SCRYPT_P),
        b64encode(salt).decode(),
        b64encode(digest).decode(),
    )
    return HASH_SEPARATOR.join(parts)


def verify_password(raw: str, stored: str | None) -> bool:
    """Check a plaintext against a stored encoding, returning False on any problem.

    Args:
        raw: Plaintext password supplied at login.
        stored: A previously produced encoding, or any other value — a foreign
            hash format, an empty string, or None.

    Returns:
        True only when ``stored`` is a well-formed encoding produced by
        :func:`hash_password` and matches ``raw``.
    """
    if not stored:
        return False
    parts = stored.split(HASH_SEPARATOR)
    if len(parts) != HASH_PARTS or parts[0] != HASH_PREFIX:
        return False
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt = b64decode(parts[4], validate=True)
        expected = b64decode(parts[5], validate=True)
        if not salt or not expected:
            return False
        return hmac.compare_digest(
            _derive(raw, salt, n, r, p), expected
        )
    except (
        ValueError,
        TypeError,
        BinasciiError,
        MemoryError,
        OverflowError,
    ):
        return False
