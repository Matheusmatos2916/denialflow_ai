from __future__ import annotations

import sqlite3

from fastapi import APIRouter, File, HTTPException, UploadFile

from denialflow_ai.api.deps import DbConn
from denialflow_ai.repositories import BatchRepository, ClaimRepository
from denialflow_ai.schemas import ClaimsUploadResponse
from denialflow_ai.services.csv_ingest import parse_claims_csv

router = APIRouter(prefix="/claims", tags=["claims"])


@router.post("/upload", response_model=ClaimsUploadResponse)
async def upload_claims(
    conn: DbConn,
    file: UploadFile = File(...),
) -> ClaimsUploadResponse:
    raw = await file.read()
    parsed = parse_claims_csv(raw, file.filename or "upload.csv")
    batch_repo = BatchRepository(conn)
    claim_repo = ClaimRepository(conn)
    if not parsed.rows and parsed.errors:
        return ClaimsUploadResponse(
            batch_id="",
            filename=parsed.filename,
            accepted_rows=0,
            errors=parsed.errors,
        )
    batch_id = await batch_repo.create(parsed.filename, len(parsed.rows))
    try:
        await claim_repo.insert_many(batch_id, parsed.rows)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "duplicate_claim_ids_in_batch: the CSV contains repeated claim_id values. "
                "Remove duplicates or use a fresh file."
            ),
        ) from exc
    return ClaimsUploadResponse(
        batch_id=batch_id,
        filename=parsed.filename,
        accepted_rows=len(parsed.rows),
        errors=parsed.errors,
    )


@router.get("")
async def list_claims(conn: DbConn, limit: int = 200, status: str | None = None):
    repo = ClaimRepository(conn)
    rows = await repo.list_all(limit=limit, status=status)
    return {"items": rows}


@router.get("/summary")
async def claims_summary(conn: DbConn, limit: int = 200):
    cur = await conn.execute(
        """
        WITH cls AS (
            SELECT claim_internal_id, category, confidence,
                   ROW_NUMBER() OVER (PARTITION BY claim_internal_id ORDER BY created_at DESC) AS rn
            FROM classification_results
        ),
        pri AS (
            SELECT claim_internal_id, priority_score, estimated_recoverable_revenue, recommended_action,
                   ROW_NUMBER() OVER (PARTITION BY claim_internal_id ORDER BY created_at DESC) AS rn
            FROM prioritization_results
        )
        SELECT
            c.id AS internal_id,
            c.claim_id,
            c.payer,
            c.denial_reason_text AS denial_reason,
            c.status,
            cr.category AS ai_category,
            cr.confidence AS classification_confidence,
            pr.priority_score,
            pr.estimated_recoverable_revenue AS recoverable_amount,
            pr.recommended_action,
            (
                SELECT a.id FROM appeals a
                WHERE a.claim_internal_id = c.id
                ORDER BY a.created_at DESC LIMIT 1
            ) AS appeal_id
        FROM claims c
        LEFT JOIN cls cr ON cr.claim_internal_id = c.id AND cr.rn = 1
        LEFT JOIN pri pr ON pr.claim_internal_id = c.id AND pr.rn = 1
        ORDER BY c.updated_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = await cur.fetchall()
    return {"items": [dict(r) for r in rows]}
