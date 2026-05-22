from __future__ import annotations

# Before other imports: Windows cp1252 consoles break on AgentOps emoji logs.
from denialflow_ai.core.logging import configure_stdout_utf8

configure_stdout_utf8()

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from denialflow_ai.api.deps import get_current_principal
from denialflow_ai.api.routers import appeals, claims, metrics, workflows
from denialflow_ai.core.config import get_settings
from denialflow_ai.core.logging import (
    configure_logging,
    get_logger,
    patch_agentops_stdio_encoding,
)
from denialflow_ai.db.connection import init_database
from denialflow_ai.llm.embeddings import require_openai_api_key_for_embeddings
from denialflow_ai.observability.agentops_client import mark_initialized
from denialflow_ai.observability.middleware import RequestContextMiddleware

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    settings.validate_auth_config()

    agentops_active = False
    if settings.agentops_should_init:
        try:
            import agentops

            # CrewAI auto-instruments after init; per-run sessions in agentops_client.
            agentops.init(
                api_key=settings.agentops_api_key,
                default_tags=settings.agentops_tags_list,
                auto_start_session=False,
            )
            patch_agentops_stdio_encoding()
            mark_initialized()
            agentops_active = True
            logger.info("agentops_initialized", tags=settings.agentops_tags_list)
        except Exception as e:  # noqa: BLE001
            logger.warning("agentops_init_failed", error=str(e))

    await init_database()
    if settings.llm_provider.strip().lower() == "groq":
        require_openai_api_key_for_embeddings()
    logger.info("denialflow_startup_complete")
    yield

    if agentops_active:
        try:
            import agentops

            agentops.end_all_sessions()
        except Exception as e:  # noqa: BLE001
            logger.warning("agentops_shutdown_failed", error=str(e))


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
    auth_dep = [Depends(get_current_principal)]
    app.include_router(claims.router, prefix="/v1", dependencies=auth_dep)
    app.include_router(workflows.router, prefix="/v1", dependencies=auth_dep)
    app.include_router(appeals.router, prefix="/v1", dependencies=auth_dep)
    app.include_router(metrics.router, prefix="/v1", dependencies=auth_dep)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
