"""Password hashing, e-mail normalisation and password policy.

Passwords are never stored or logged in plain text. Each password gets its own
random salt and is stretched with PBKDF2-HMAC-SHA256 (260 000 iterations,
the OWASP 2023 recommendation for this algorithm).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 260_000
SALT_BYTES = 16

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
MIN_PASSWORD_LENGTH = 8


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.fullmatch(normalize_email(email)))


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"{ALGORITHM}${ITERATIONS}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of a password against the stored hash."""
    try:
        algorithm, iterations, salt_b64, hash_b64 = (stored or "").split("$")
        if algorithm != ALGORITHM:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def password_problems(password: str) -> list[str]:
    """Return a list of policy violations (empty list = password is acceptable)."""
    problems: list[str] = []
    if len(password or "") < MIN_PASSWORD_LENGTH:
        problems.append(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if not re.search(r"[A-Za-z]", password or ""):
        problems.append("Add at least one letter.")
    if not re.search(r"\d", password or ""):
        problems.append("Add at least one digit.")
    if password and password.strip() != password:
        problems.append("Remove spaces at the beginning or the end.")
    return problems


def generate_invite_code(length: int = 6) -> str:
    """Human-friendly invite code without ambiguous characters (0/O, 1/I)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))
