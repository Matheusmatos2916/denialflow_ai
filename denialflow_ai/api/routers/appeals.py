from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException

from denialflow_ai.api.deps import CurrentPrincipal, DbConn
from denialflow_ai.core.config import get_settings
from denialflow_ai.core.logging import get_logger
from denialflow_ai.crews.appeal import strip_confidence_line
from denialflow_ai.services.appeal_letter_context import sanitize_appeal_body
from denialflow_ai.crews.appeal_review import run_appeal_second_opinion
from denialflow_ai.services.appeal_letter_context import (
    build_letter_context,
    format_letter_context_block,
)
from denialflow_ai.services.gmail_notify import (
    AppealDecision,
    send_appeal_decision_email,
)
from denialflow_ai.repositories import (
    AnalysisRepository,
    AppealRepository,
    AuditRepository,
    ClaimRepository,
)
from denialflow_ai.schemas import (
    AppealAIReview,
    AppealDetail,
    AppealRejectRequest,
    AppealReviewEditRequest,
    ClassificationResult,
    PrioritizationResult,
    RagHit,
)

router = APIRouter(prefix="/appeals", tags=["appeals"])
logger = get_logger(__name__)


async def _notify_appeal_email(
    conn: DbConn,
    *,
    appeal_id: str,
    claim_internal_id: str,
    claim_id: str,
    decision: AppealDecision,
    body_text: str,
    edit_reason: str | None = None,
) -> None:
    try:
        result = await send_appeal_decision_email(
            appeal_id=appeal_id,
            claim_id=claim_id,
            decision=decision,
            body_text=body_text,
            edit_reason=edit_reason,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "gmail_notify_failed",
            appeal_id=appeal_id,
            claim_id=claim_id,
            decision=decision,
            error=str(e),
        )
        await AuditRepository(conn).append(
            "appeal",
            appeal_id,
            "system",
            "email_failed",
            {
                "claim_internal_id": claim_internal_id,
                "decision": decision,
                "error": str(e),
            },
        )
        if get_settings().gmail_fail_on_error:
            raise HTTPException(status_code=502, detail="gmail_notify_failed") from e
        return

    if not result.get("sent"):
        await AuditRepository(conn).append(
            "appeal",
            appeal_id,
            "system",
            "email_skipped",
            {
                "claim_internal_id": claim_internal_id,
                "decision": decision,
                "reason": result.get("reason"),
            },
        )
        return

    await AuditRepository(conn).append(
        "appeal",
        appeal_id,
        "system",
        "email_sent",
        {
            "claim_internal_id": claim_internal_id,
            "decision": decision,
            "to": result.get("to"),
        },
    )


async def _build_appeal_detail(row: dict, conn: DbConn) -> AppealDetail:
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

    ai_review: AppealAIReview | None = None
    raw_review = row.get("ai_review_json")
    if raw_review:
        try:
            ai_review = AppealAIReview.model_validate(json.loads(raw_review))
        except Exception:  # noqa: BLE001
            ai_review = None

    return AppealDetail(
        id=row["id"],
        claim_internal_id=row["claim_internal_id"],
        claim_id=claim["claim_id"],
        status=row["status"],
        draft_text=strip_confidence_line(row["draft_text"] or ""),
        final_text=strip_confidence_line(row["final_text"] or "") or None,
        confidence=float(row["confidence"]),
        citations=hits,
        classification=cls,
        prioritization=pri,
        model_used=row["model_used"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        ai_review=ai_review,
        ai_review_at=row.get("ai_review_at"),
    )


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
    return await _build_appeal_detail(row, conn)


@router.post("/{appeal_id}/ai-review", response_model=AppealAIReview)
async def appeal_ai_review(appeal_id: str, conn: DbConn) -> AppealAIReview:
    """Bedrock second opinion on the CrewAI/Groq draft (does not auto-approve)."""
    if not get_settings().bedrock_review_enabled:
        raise HTTPException(status_code=503, detail="bedrock_review_disabled")

    appeals = AppealRepository(conn)
    row = await appeals.get(appeal_id)
    if not row:
        raise HTTPException(status_code=404, detail="appeal_not_found")

    detail = await _build_appeal_detail(row, conn)
    if not (detail.draft_text or "").strip():
        raise HTTPException(status_code=400, detail="draft_text_empty")

    claim = await ClaimRepository(conn).get_by_internal_id(row["claim_internal_id"])
    letter_context = ""
    if claim:
        letter_context = format_letter_context_block(build_letter_context(claim))

    try:
        review = await asyncio.to_thread(
            run_appeal_second_opinion,
            detail,
            letter_context,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        msg = str(e)
        if msg == "bedrock_quota_exceeded":
            raise HTTPException(
                status_code=429,
                detail=(
                    "bedrock_quota_exceeded: cota diária de tokens do Bedrock esgotada. "
                    "Aguarde o reset (UTC), solicite aumento de quota no console AWS, "
                    "ou defina BEDROCK_REVIEW_FALLBACK_GROQ=true no .env."
                ),
            ) from e
        raise HTTPException(status_code=503, detail=msg) from e
    except Exception as e:  # noqa: BLE001
        from denialflow_ai.crews.llm_config import (
            is_bedrock_rate_limit_error,
            is_groq_rate_limit_error,
        )

        if is_groq_rate_limit_error(e):
            raise HTTPException(
                status_code=429,
                detail=(
                    "groq_rate_limit_exceeded: cota diária de tokens do Groq esgotada "
                    "(PRIMARY, FALLBACK e APPEAL). Aguarde o reset indicado na mensagem "
                    "do provedor ou altere GROQ_MODEL_* no .env."
                ),
            ) from e
        if is_bedrock_rate_limit_error(e):
            raise HTTPException(
                status_code=429,
                detail=(
                    "bedrock_quota_exceeded: cota diária de tokens do Bedrock esgotada. "
                    "Aguarde o reset (UTC), solicite aumento de quota no console AWS, "
                    "ou defina BEDROCK_REVIEW_FALLBACK_GROQ=true no .env."
                ),
            ) from e
        raise HTTPException(status_code=502, detail=f"bedrock_review_failed: {e}") from e

    model_label = review.model_used or get_settings().bedrock_model_review
    await appeals.save_ai_review(
        appeal_id,
        review.model_dump_json(),
        model_label,
    )
    await AuditRepository(conn).append(
        "appeal",
        appeal_id,
        "bedrock",
        "second_opinion",
        {
            "claim_internal_id": row["claim_internal_id"],
            "recommended_action": review.recommended_action,
            "overall_score": review.overall_score,
            "model_used": model_label,
        },
    )
    return review


@router.post("/{appeal_id}/approve")
async def approve_appeal(appeal_id: str, conn: DbConn, principal: CurrentPrincipal):
    appeals = AppealRepository(conn)
    row = await appeals.get(appeal_id)
    if not row:
        raise HTTPException(status_code=404, detail="appeal_not_found")
    await appeals.approve(appeal_id)
    await ClaimRepository(conn).update_status(row["claim_internal_id"], "approved")
    actor = principal.get("sub", "human")
    await AuditRepository(conn).append(
        "appeal",
        appeal_id,
        actor,
        "approve",
        {"claim_internal_id": row["claim_internal_id"]},
    )
    claim = await ClaimRepository(conn).get_by_internal_id(row["claim_internal_id"])
    claim_id = claim["claim_id"] if claim else row["claim_internal_id"]
    final_text = sanitize_appeal_body(strip_confidence_line(row["draft_text"] or ""))
    await _notify_appeal_email(
        conn,
        appeal_id=appeal_id,
        claim_internal_id=row["claim_internal_id"],
        claim_id=claim_id,
        decision="approved",
        body_text=final_text,
    )
    return {"ok": True, "status": "approved"}


@router.post("/{appeal_id}/reject")
async def reject_appeal(
    appeal_id: str,
    body: AppealRejectRequest,
    conn: DbConn,
    principal: CurrentPrincipal,
):
    appeals = AppealRepository(conn)
    row = await appeals.get(appeal_id)
    if not row:
        raise HTTPException(status_code=404, detail="appeal_not_found")
    await appeals.reject(appeal_id)
    await ClaimRepository(conn).update_status(row["claim_internal_id"], "rejected")
    actor = principal.get("sub", "human")
    await AuditRepository(conn).append(
        "appeal",
        appeal_id,
        actor,
        "reject",
        {"reason": body.reason},
    )
    return {"ok": True, "status": "rejected"}


@router.post("/{appeal_id}/edit")
async def edit_appeal(
    appeal_id: str,
    body: AppealReviewEditRequest,
    conn: DbConn,
    principal: CurrentPrincipal,
):
    appeals = AppealRepository(conn)
    row = await appeals.get(appeal_id)
    if not row:
        raise HTTPException(status_code=404, detail="appeal_not_found")
    await appeals.edit(appeal_id, body.final_text)
    await ClaimRepository(conn).update_status(row["claim_internal_id"], "edited")
    actor = principal.get("sub", "human")
    await AuditRepository(conn).append(
        "appeal",
        appeal_id,
        actor,
        "edit",
        {"reason": body.reason, "length": len(body.final_text)},
    )
    claim = await ClaimRepository(conn).get_by_internal_id(row["claim_internal_id"])
    claim_id = claim["claim_id"] if claim else row["claim_internal_id"]
    final_text = sanitize_appeal_body(strip_confidence_line(body.final_text))
    await _notify_appeal_email(
        conn,
        appeal_id=appeal_id,
        claim_internal_id=row["claim_internal_id"],
        claim_id=claim_id,
        decision="edited",
        body_text=final_text,
        edit_reason=body.reason,
    )
    return {"ok": True, "status": "edited"}
