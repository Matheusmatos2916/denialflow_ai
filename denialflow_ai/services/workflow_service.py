from __future__ import annotations

import asyncio
import json
from typing import Any

from denialflow_ai.core.logging import get_logger
from denialflow_ai.observability.agentops_client import (
    workflow_tags,
    agentops_trace_context,
    bind_workflow_context,
)
from denialflow_ai.crews.appeal import run_research_and_appeal
from denialflow_ai.crews.classification import run_denial_classification
from denialflow_ai.crews.prioritization import run_financial_prioritization
from denialflow_ai.db.connection import get_connection
from denialflow_ai.rag import retrieve_for_claim
from denialflow_ai.repositories import (
    AnalysisRepository,
    AppealRepository,
    AuditRepository,
    ClaimRepository,
    WorkflowRepository,
)
from denialflow_ai.services.appeal_letter_context import (
    build_letter_context,
    format_letter_context_block,
    has_bracket_placeholders,
    sanitize_appeal_body,
)
from denialflow_ai.schemas import ClaimStatus, WorkflowRunStatus

logger = get_logger(__name__)


def _claim_text(row: dict[str, Any]) -> str:
    payload = {
        "claim_id": row.get("claim_id"),
        "payer": row.get("payer"),
        "denial_code": row.get("denial_code"),
        "denial_reason_text": row.get("denial_reason_text"),
        "billed_amount": row.get("billed_amount"),
        "allowed_amount": row.get("allowed_amount"),
        "patient_balance": row.get("patient_balance"),
        "aging_days": row.get("aging_days"),
        "specialty": row.get("specialty"),
        "cpt_codes": row.get("cpt_codes"),
        "icd10_codes": row.get("icd10_codes"),
        "service_date": row.get("service_date"),
        "remark_codes": row.get("remark_codes"),
    }
    return json.dumps(payload, indent=2)


def _rough_tokens(text: str) -> int:
    return max(1, len(text) // 4)


async def execute_workflow_run(*, run_id: str, batch_id: str, max_claims: int) -> None:
    tags = workflow_tags(run_id=run_id, batch_id=batch_id, phase="workflow")
    with agentops_trace_context(trace_name=f"workflow-{run_id}", tags=tags):
        await _execute_workflow_run_body(
            run_id=run_id,
            batch_id=batch_id,
            max_claims=max_claims,
        )


async def _execute_workflow_run_body(*, run_id: str, batch_id: str, max_claims: int) -> None:
    bind_workflow_context(run_id=run_id, batch_id=batch_id, phase="workflow")
    conn = await get_connection()
    wf = WorkflowRepository(conn)
    claims_repo = ClaimRepository(conn)
    analysis = AnalysisRepository(conn)
    appeals_repo = AppealRepository(conn)
    audit = AuditRepository(conn)
    budget_used = 0
    settings_budget = __import__("denialflow_ai.core.config", fromlist=["get_settings"]).get_settings().workflow_token_budget

    try:
        rows = await claims_repo.list_for_batch(batch_id, limit=max_claims, status="pending")
        if not rows:
            await wf.add_event(run_id, "workflow", "No pending claims in batch", payload={"batch_id": batch_id})
            await wf.complete_run(run_id, WorkflowRunStatus.COMPLETED.value)
            return

        await wf.add_event(
            run_id,
            "workflow",
            f"Starting processing for {len(rows)} claim(s)",
            payload={"count": len(rows)},
        )

        for row in rows:
            cid = row["id"]
            claim_key = row["claim_id"]
            bind_workflow_context(
                run_id=run_id,
                batch_id=batch_id,
                claim_id=claim_key,
                phase="claim",
            )
            payload = _claim_text(row)
            budget_used += _rough_tokens(payload)

            await wf.add_event(run_id, "classification", f"Classifying {claim_key}", payload={})
            cls, cls_model = await asyncio.to_thread(run_denial_classification, payload)
            budget_used += _rough_tokens(cls.model_dump_json())
            if budget_used > settings_budget:
                await wf.add_event(
                    run_id,
                    "budget",
                    "Token budget exceeded — stopping batch early",
                    level="warning",
                    payload={"budget_used": budget_used},
                )
                break

            await analysis.save_classification(
                cid,
                cls.category,
                float(cls.confidence),
                cls.explanation,
                cls_model,
            )
            await claims_repo.update_status(cid, ClaimStatus.CLASSIFIED.value)
            await audit.append(
                "claim",
                cid,
                "system",
                "classification_completed",
                {"claim_id": claim_key, "category": cls.category, "model": cls_model},
            )

            cls_summary = f"{cls.category} ({cls.confidence:.2f}): {cls.explanation[:500]}"

            await wf.add_event(run_id, "prioritization", f"Prioritizing {claim_key}", payload={})
            pri, pri_model = await asyncio.to_thread(run_financial_prioritization, payload, cls_summary)
            budget_used += _rough_tokens(pri.model_dump_json())

            await analysis.save_prioritization(
                cid,
                float(pri.priority_score),
                float(pri.estimated_recoverable_revenue),
                float(pri.urgency),
                float(pri.reversal_probability),
                pri.recommended_action,
                pri_model,
            )
            await claims_repo.update_status(cid, ClaimStatus.PRIORITIZED.value)

            await wf.add_event(run_id, "rag", f"Retrieving precedents for {claim_key}", payload={})
            rag_query = (
                f"{row.get('payer','')} denial {row.get('denial_code','')}: "
                f"{row.get('denial_reason_text','')[:500]}"
            )
            try:
                rag = await retrieve_for_claim(rag_query)
            except Exception as e:  # noqa: BLE001
                logger.warning("rag_failed", error=str(e), claim_id=claim_key)
                rag = await retrieve_for_claim(claim_key)  # minimal fallback query
            await analysis.save_rag(cid, rag_query, rag.model_dump_json())
            await claims_repo.update_status(cid, ClaimStatus.RETRIEVED.value)

            pri_summary = (
                f"priority={pri.priority_score:.1f}; recoverable={pri.estimated_recoverable_revenue:.2f}; "
                f"P(reversal)={pri.reversal_probability:.2f}; action={pri.recommended_action[:300]}"
            )

            letter_block = format_letter_context_block(build_letter_context(row))

            await wf.add_event(run_id, "appeal", f"Drafting appeal for {claim_key}", payload={})
            appeal_text, appeal_conf, appeal_model = await asyncio.to_thread(
                run_research_and_appeal,
                payload,
                cls_summary,
                pri_summary,
                letter_block,
            )
            appeal_text = sanitize_appeal_body(appeal_text)
            if has_bracket_placeholders(appeal_text):
                logger.warning(
                    "appeal_bracket_placeholders",
                    claim_id=claim_key,
                    model=appeal_model,
                )
            budget_used += _rough_tokens(appeal_text)

            appeal_id = await appeals_repo.create_draft(
                claim_internal_id=cid,
                draft_text=appeal_text,
                citations_json=rag.model_dump_json(),
                confidence=float(appeal_conf),
                model_used=str(appeal_model),
                status=ClaimStatus.AWAITING_REVIEW.value,
            )
            await claims_repo.update_status(cid, ClaimStatus.AWAITING_REVIEW.value)
            await audit.append(
                "appeal",
                appeal_id,
                "system",
                "appeal_draft_created",
                {
                    "claim_id": claim_key,
                    "model": appeal_model,
                    "cited_docs": [h.doc_id for h in rag.hits],
                },
            )
            await wf.add_event(
                run_id,
                "hitl",
                f"Awaiting human review for appeal {appeal_id}",
                payload={"appeal_id": appeal_id, "claim_id": claim_key},
            )

        await wf.complete_run(run_id, WorkflowRunStatus.COMPLETED.value)
    except Exception as e:  # noqa: BLE001
        logger.exception("workflow_failed", run_id=run_id, error=str(e))
        await wf.add_event(run_id, "error", str(e), level="error", payload={})
        await wf.complete_run(run_id, WorkflowRunStatus.FAILED.value, error=str(e))
    finally:
        await conn.close()
