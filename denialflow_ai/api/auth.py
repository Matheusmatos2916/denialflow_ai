from __future__ import annotations

import secrets
import hashlib
import hmac
import base64
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import HTTPException, status

from denialflow_ai.core.config import get_settings

PASSWORD_ITERATIONS = 310_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            base64.urlsafe_b64decode(salt.encode()),
            int(iterations),
        )
        return hmac.compare_digest(
            actual, base64.urlsafe_b64decode(expected.encode())
        )
    except (ValueError, TypeError):
        return False


def _looks_like_jwt(token: str) -> bool:
    parts = token.split(".")
    return len(parts) == 3 and all(parts)


def create_access_token(
    *,
    subject: str = "api",
    expires_days: int = 365,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    settings = get_settings()
    secret = settings.jwt_secret.strip()
    if not secret:
        raise ValueError("JWT_SECRET is required to create access tokens")
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(days=expires_days),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)


def verify_bearer_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.jwt_auth_enabled:
        return {"sub": "anonymous"}

    raw = token.strip()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    configured = settings.api_access_token.strip()
    if configured and secrets.compare_digest(raw, configured):
        return {"sub": "api", "auth": "static"}

    secret = settings.jwt_secret.strip()
    if secret and _looks_like_jwt(raw):
        try:
            return jwt.decode(
                raw,
                secret,
                algorithms=[settings.jwt_algorithm],
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            ) from exc

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid bearer token",
    )
