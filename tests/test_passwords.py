"""scrypt password hashing: round-trip and rejection of foreign formats."""

from litestar_admin import hash_password, verify_password
from litestar_admin.constants import PASSWORD_MAX_LENGTH

DJANGO_HASH = "pbkdf2_sha256$390000$abc123$Zm9vYmFyYmF6cXV1eA=="


def test_hash_round_trip() -> None:
    """A hashed password verifies against its own plaintext."""
    assert verify_password("correct horse", hash_password("correct horse")) is True


def test_wrong_password_rejected() -> None:
    """A different plaintext does not verify."""
    assert verify_password("wrong horse", hash_password("correct horse")) is False


def test_encoding_fits_a_128_char_column() -> None:
    """Hosts may store this in String(128); dklen=32 keeps it to 86 chars."""
    assert len(hash_password("correct horse")) <= PASSWORD_MAX_LENGTH


def test_salt_is_random() -> None:
    """Hashing the same plaintext twice yields different encodings."""
    assert hash_password("same") != hash_password("same")


def test_django_hash_rejected() -> None:
    """A legacy Django pbkdf2 hash never verifies; there is no fallback path."""
    assert verify_password("correct horse", DJANGO_HASH) is False


def test_malformed_values_rejected() -> None:
    """Missing, empty and broken values return False, never raise."""
    assert verify_password("x", None) is False
    assert verify_password("x", "") is False
    assert verify_password("x", "scrypt$notanumber$8$1$aaaa$bbbb") is False
    assert verify_password("x", "scrypt$16384$8$1") is False
    assert verify_password("x", "scrypt$16384$8$1$!!!$!!!") is False


def test_invalid_scrypt_parameters_rejected() -> None:
    """Semantically invalid scrypt parameters return False, never raise."""
    # Valid 16-byte salt and 32-byte digest in base64; only scrypt params vary.
    salt_b64 = "AAAAAAAAAAAAAAAAAAAAAA=="
    digest_b64 = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    # n not a power of 2
    assert (
        verify_password("x", f"scrypt$3$8$1${salt_b64}${digest_b64}") is False
    )
    # n = 0
    assert (
        verify_password("x", f"scrypt$0$8$1${salt_b64}${digest_b64}") is False
    )
    # r = 0
    assert (
        verify_password("x", f"scrypt$16384$0$1${salt_b64}${digest_b64}")
        is False
    )
    # p = 0
    assert (
        verify_password("x", f"scrypt$16384$8$0${salt_b64}${digest_b64}")
        is False
    )
