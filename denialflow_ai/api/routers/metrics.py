from __future__ import annotations

from fastapi import APIRouter

from denialflow_ai.api.deps import DbConn
from denialflow_ai.observability import get_metrics
from denialflow_ai.schemas import DashboardMetrics

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/dashboard", response_model=DashboardMetrics)
async def dashboard(conn: DbConn) -> DashboardMetrics:
    cur = await conn.execute("SELECT COUNT(*) AS c FROM claims")
    total = int((await cur.fetchone())["c"])

    cur = await conn.execute(
        "SELECT AVG(CASE WHEN denial_reason_text IS NOT NULL AND denial_reason_text != '' "
        "THEN 1.0 ELSE 0.0 END) AS rate FROM claims"
    )
    row = await cur.fetchone()
    denial_rate = float(row["rate"] or 0.0) if row else 0.0

    cur = await conn.execute(
        """
        SELECT SUM(p.estimated_recoverable_revenue) AS s
        FROM prioritization_results p
        INNER JOIN (
            SELECT claim_internal_id, MAX(created_at) AS mx
            FROM prioritization_results
            GROUP BY claim_internal_id
        ) t ON t.claim_internal_id = p.claim_internal_id AND t.mx = p.created_at
        """
    )
    row = await cur.fetchone()
    recoverable = float(row["s"] or 0.0) if row else 0.0

    cur = await conn.execute(
        "SELECT COUNT(*) AS c FROM appeals WHERE status = 'awaiting_review'"
    )
    awaiting = int((await cur.fetchone())["c"])

    cur = await conn.execute(
        """
        SELECT AVG(
            (julianday(completed_at) - julianday(started_at)) * 86400000.0
        ) AS ms
        FROM workflow_runs
        WHERE completed_at IS NOT NULL AND status = 'completed'
        """
    )
    row = await cur.fetchone()
    avg_ms = float(row["ms"]) if row and row["ms"] is not None else None

    cur = await conn.execute(
        """
        SELECT COUNT(*) AS c FROM workflow_runs
        WHERE substr(started_at, 1, 10) >= date('now', '-1 day')
        """
    )
    runs_24h = int((await cur.fetchone())["c"])

    cur = await conn.execute(
        """
        SELECT c.claim_id, p.priority_score, p.estimated_recoverable_revenue, c.payer
        FROM prioritization_results p
        INNER JOIN (
            SELECT claim_internal_id, MAX(created_at) AS mx
            FROM prioritization_results
            GROUP BY claim_internal_id
        ) t ON t.claim_internal_id = p.claim_internal_id AND t.mx = p.created_at
        INNER JOIN claims c ON c.id = p.claim_internal_id
        ORDER BY p.priority_score DESC
        LIMIT 10
        """
    )
    pq = await cur.fetchall()
    priority_queue_top = [dict(r) for r in pq]

    snap = get_metrics().snapshot()
    if avg_ms is None and snap.get("avg_latency_ms_recent"):
        avg_ms = float(snap["avg_latency_ms_recent"])

    return DashboardMetrics(
        total_claims=total,
        denial_rate_proxy=denial_rate,
        recoverable_revenue_sum=recoverable,
        awaiting_review=awaiting,
        avg_run_duration_ms=avg_ms,
        runs_last_24h=runs_24h,
        priority_queue_top=priority_queue_top,
    )


@router.get("/ops")
async def ops_snapshot():
    return get_metrics().snapshot()
