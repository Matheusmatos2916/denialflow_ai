from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from denialflow_ai.api.deps import DbConn
from denialflow_ai.observability import get_metrics
from denialflow_ai.repositories import BatchRepository, WorkflowRepository
from denialflow_ai.schemas import WorkflowRunRequest, WorkflowRunResponse, WorkflowRunStatus
from denialflow_ai.services.workflow_service import execute_workflow_run

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("/run", response_model=WorkflowRunResponse)
async def run_workflow(
    body: WorkflowRunRequest,
    conn: DbConn,
    background_tasks: BackgroundTasks,
) -> WorkflowRunResponse:
    batch = await BatchRepository(conn).get(body.batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="batch_not_found")
    wf = WorkflowRepository(conn)
    run_id = await wf.create_run(
        body.batch_id,
        {"max_claims": body.max_claims},
    )
    get_metrics().inc_workflow()
    background_tasks.add_task(
        execute_workflow_run,
        run_id=run_id,
        batch_id=body.batch_id,
        max_claims=body.max_claims,
    )
    return WorkflowRunResponse(
        run_id=run_id,
        batch_id=body.batch_id,
        status=WorkflowRunStatus.RUNNING,
    )


@router.get("/{run_id}")
async def get_run(run_id: str, conn: DbConn):
    row = await WorkflowRepository(conn).get_run(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="run_not_found")
    return row


@router.get("/{run_id}/events")
async def get_events(run_id: str, conn: DbConn, limit: int = 200):
    return {"items": await WorkflowRepository(conn).list_events(run_id, limit=limit)}


@router.get("")
async def list_runs(conn: DbConn, limit: int = 50):
    return {"items": await WorkflowRepository(conn).list_recent_runs(limit=limit)}
