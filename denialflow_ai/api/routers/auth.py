from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from denialflow_ai.api.auth import create_access_token, hash_password, verify_password
from denialflow_ai.core.config import get_settings
from denialflow_ai.db.connection import get_connection

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, str]


def _email(value: str) -> str:
    normalized = value.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    return normalized


def _response(user_id: str, name: str, email: str) -> AuthResponse:
    settings = get_settings()
    return AuthResponse(
        access_token=create_access_token(
            subject=user_id,
            extra_claims={"email": email, "name": name},
        ),
        user={"id": user_id, "name": name, "email": email},
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest) -> AuthResponse:
    email = _email(payload.email)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    user_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    db = await get_connection()
    try:
        try:
            await db.execute(
                "INSERT INTO users (id, name, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, name, email, hash_password(payload.password), now),
            )
            await db.commit()
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise HTTPException(status_code=409, detail="An account with this email already exists") from exc
            raise
    finally:
        await db.close()
    return _response(user_id, name, email)


@router.post("/login", response_model=AuthResponse)
async def login(payload: LoginRequest) -> AuthResponse:
    email = _email(payload.email)
    db = await get_connection()
    try:
        cursor = await db.execute(
            "SELECT id, name, email, password_hash FROM users WHERE email = ? COLLATE NOCASE",
            (email,),
        )
        user = await cursor.fetchone()
    finally:
        await db.close()
    if user is None or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return _response(user["id"], user["name"], user["email"])


@router.get("/me")
async def me():
    return {"status": "authenticated"}