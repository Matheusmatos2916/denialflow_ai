from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from denialflow_ai.api.deps import DbConn
from denialflow_ai.repositories import (
    AnalysisRepository,
    AppealRepository,
    AuditRepository,
    ClaimRepository,
)
from denialflow_ai.schemas import (
    AppealDetail,
    AppealRejectRequest,
    AppealReviewEditRequest,
    ClassificationResult,
    PrioritizationResult,
    RagHit,
)

router = APIRouter(prefix="/appeals", tags=["appeals"])


@router.get("")
async def list_appeals(conn: DbConn, status: str | None = "awaiting_review", limit: int = 100):
    repo = AppealRepository(conn)
    if status:
        cur = await conn.execute(
            "SELECT * FROM appeals WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
            (status, limit),
        )
        rows = await cur.fetchall()
        return {"items": [dict(r) for r in rows]}
    return {"items": await repo.list_awaiting(limit=limit)}


@router.get("/{appeal_id}", response_model=AppealDetail)
async def get_appeal(appeal_id: str, conn: DbConn) -> AppealDetail:
    appeals = AppealRepository(conn)
    row = await appeals.get(appeal_id)
    if not row:
        raise HTTPException(status_code=404, detail="appeal_not_found")
    claim = await ClaimRepository(conn).get_by_internal_id(row["claim_internal_id"])
    if not claim:
        raise HTTPException(status_code=404, detail="claim_not_found")

    analysis = AnalysisRepository(conn)
    cls_row = await analysis.latest_classification(row["claim_internal_id"])
    pri_row = await analysis.latest_prioritization(row["claim_internal_id"])

    citations_raw = json.loads(row["citations_json"] or "{}")
    hits = [RagHit.model_validate(h) for h in citations_raw.get("hits", [])]

    cls = (
        ClassificationResult(
            category=cls_row["category"],
            confidence=float(cls_row["confidence"]),
            explanation=cls_row["explanation"],
        )
        if cls_row
        else None
    )
    pri = (
        PrioritizationResult(
            priority_score=float(pri_row["priority_score"]),
            estimated_recoverable_revenue=float(pri_row["estimated_recoverable_revenue"]),
            urgency=float(pri_row["urgency"]),
            reversal_probability=float(pri_row["reversal_probability"]),
            recommended_action=pri_row["recommended_action"],
        )
        if pri_row
        else None
    )

    return AppealDetail(
        id=row["id"],
        claim_internal_id=row["claim_internal_id"],
        claim_id=claim["claim_id"],
        status=row["status"],
        draft_text=row["draft_text"],
        final_text=row["final_text"],
        confidence=float(row["confidence"]),
        citations=hits,
        classification=cls,
        prioritization=pri,
        model_used=row["model_used"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.post("/{appeal_id}/approve")
async def approve_appeal(appeal_id: str, conn: DbConn):
    appeals = AppealRepository(conn)
    row = await appeals.get(appeal_id)
    if not row:
        raise HTTPException(status_code=404, detail="appeal_not_found")
    await appeals.approve(appeal_id)
    await ClaimRepository(conn).update_status(row["claim_internal_id"], "approved")
    await AuditRepository(conn).append(
        "appeal",
        appeal_id,
        "human",
        "approve",
        {"claim_internal_id": row["claim_internal_id"]},
    )
    return {"ok": True, "status": "approved"}


@router.post("/{appeal_id}/reject")
async def reject_appeal(appeal_id: str, body: AppealRejectRequest, conn: DbConn):
    appeals = AppealRepository(conn)
    row = await appeals.get(appeal_id)
    if not row:
        raise HTTPException(status_code=404, detail="appeal_not_found")
    await appeals.reject(appeal_id)
    await ClaimRepository(conn).update_status(row["claim_internal_id"], "rejected")
    await AuditRepository(conn).append(
        "appeal",
        appeal_id,
        "human",
        "reject",
        {"reason": body.reason},
    )
    return {"ok": True, "status": "rejected"}


@router.post("/{appeal_id}/edit")
async def edit_appeal(appeal_id: str, body: AppealReviewEditRequest, conn: DbConn):
    appeals = AppealRepository(conn)
    row = await appeals.get(appeal_id)
    if not row:
        raise HTTPException(status_code=404, detail="appeal_not_found")
    await appeals.edit(appeal_id, body.final_text)
    await ClaimRepository(conn).update_status(row["claim_internal_id"], "edited")
    await AuditRepository(conn).append(
        "appeal",
        appeal_id,
        "human",
        "edit",
        {"reason": body.reason, "length": len(body.final_text)},
    )
    return {"ok": True, "status": "edited"}
