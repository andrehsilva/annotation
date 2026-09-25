"""Password hashing and session tokens, stdlib only (no extra dependency).

`hashlib.scrypt` ships with CPython's OpenSSL, which is why there is no passlib/bcrypt here.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import timedelta

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
KEY_BYTES = 32
MAX_N = 2**17

SESSION_DAYS = 30
SESSION_TTL = timedelta(days=SESSION_DAYS)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text.encode("ascii"))


def hash_password(password: str) -> str:
    """Stored as `scrypt$n$r$p$salt$key` so the cost can be raised later without a migration."""
    salt = secrets.token_bytes(SALT_BYTES)
    key = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=KEY_BYTES
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, key = stored.split("$")
        if scheme != "scrypt" or int(n) > MAX_N:
            return False
        expected = _unb64(key)
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError, OSError):
        return False
    return hmac.compare_digest(candidate, expected)


# Checked when the e-mail does not exist, so a failed login costs the same as a real one.
DUMMY_HASH = hash_password("notai-placeholder")


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
