from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from denialflow_ai.api.routers import appeals, claims, metrics, workflows
from denialflow_ai.core.config import get_settings
from denialflow_ai.core.logging import configure_logging, get_logger
from denialflow_ai.db.connection import init_database
from denialflow_ai.llm.embeddings import require_openai_api_key_for_embeddings
from denialflow_ai.observability.middleware import RequestContextMiddleware

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    await init_database()
    if get_settings().llm_provider.strip().lower() == "groq":
        require_openai_api_key_for_embeddings()
    logger.info("denialflow_startup_complete")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="DenialFlow AI API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(claims.router, prefix="/v1")
    app.include_router(workflows.router, prefix="/v1")
    app.include_router(appeals.router, prefix="/v1")
    app.include_router(metrics.router, prefix="/v1")
    return app


app = create_app()
