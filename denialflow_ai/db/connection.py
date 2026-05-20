from __future__ import annotations

from pathlib import Path

import aiosqlite

from denialflow_ai.core.config import get_settings


async def get_connection() -> aiosqlite.Connection:
    settings = get_settings()
    path = settings.database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(path))
    db.row_factory = aiosqlite.Row
    return db


async def init_database() -> None:
    from denialflow_ai.db import init_db  # local import avoids cycles

    settings = get_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    await init_db(str(settings.database_path))
