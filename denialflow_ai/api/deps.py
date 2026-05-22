from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Any

import aiosqlite
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from denialflow_ai.api.auth import verify_bearer_token
from denialflow_ai.core.config import get_settings
from denialflow_ai.db.connection import get_connection

security = HTTPBearer(auto_error=False)


async def db_conn() -> AsyncIterator[aiosqlite.Connection]:
    conn = await get_connection()
    try:
        yield conn
    finally:
        await conn.close()


async def get_current_principal(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> dict[str, Any]:
    if not get_settings().jwt_auth_enabled:
        return {"sub": "anonymous"}
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_bearer_token(creds.credentials)


DbConn = Annotated[aiosqlite.Connection, Depends(db_conn)]
CurrentPrincipal = Annotated[dict[str, Any], Depends(get_current_principal)]
