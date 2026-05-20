from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import aiosqlite
from fastapi import Depends

from denialflow_ai.db.connection import get_connection


async def db_conn() -> AsyncIterator[aiosqlite.Connection]:
    conn = await get_connection()
    try:
        yield conn
    finally:
        await conn.close()


DbConn = Annotated[aiosqlite.Connection, Depends(db_conn)]
