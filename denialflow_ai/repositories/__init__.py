from __future__ import annotations

import json
import uuid
from typing import Any, Sequence

import aiosqlite

from denialflow_ai.schemas import utc_now_iso


class BatchRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def create(self, filename: str, row_count: int) -> str:
        bid = str(uuid.uuid4())
        now = utc_now_iso()
        await self._conn.execute(
            "INSERT INTO batches (id, filename, row_count, created_at, status) VALUES (?, ?, ?, ?, ?)",
            (bid, filename, row_count, now, "uploaded"),
        )
        await self._conn.commit()
        return bid

    async def get(self, batch_id: str) -> dict[str, Any] | None:
        cur = await self._conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


class ClaimRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def insert_many(self, batch_id: str, rows: Sequence[dict[str, Any]]) -> None:
        now = utc_now_iso()
        for r in rows:
            cid = str(uuid.uuid4())
            await self._conn.execute(
                """
                INSERT INTO claims (
                    id, batch_id, claim_id, payer, denial_code, denial_reason_text,
                    billed_amount, allowed_amount, patient_balance, aging_days,
                    specialty, cpt_codes, icd10_codes, service_date, remark_codes,
                    provider_name, provider_address, provider_city, provider_state,
                    provider_zip, signer_name, signer_title, provider_npi,
                    payer_address, payer_city, payer_state, payer_zip, letter_date,
                    raw_json, status, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?
                )
                """,
                (
                    cid,
                    batch_id,
                    r["claim_id"],
                    r.get("payer"),
                    r.get("denial_code"),
                    r.get("denial_reason_text"),
                    r.get("billed_amount"),
                    r.get("allowed_amount"),
                    r.get("patient_balance"),
                    r.get("aging_days"),
                    r.get("specialty"),
                    r.get("cpt_codes"),
                    r.get("icd10_codes"),
                    r.get("service_date"),
                    r.get("remark_codes"),
                    r.get("provider_name"),
                    r.get("provider_address"),
                    r.get("provider_city"),
                    r.get("provider_state"),
                    r.get("provider_zip"),
                    r.get("signer_name"),
                    r.get("signer_title"),
                    r.get("provider_npi"),
                    r.get("payer_address"),
                    r.get("payer_city"),
                    r.get("payer_state"),
                    r.get("payer_zip"),
                    r.get("letter_date"),
                    json.dumps(r.get("raw") or r),
                    "pending",
                    now,
                    now,
                ),
            )
        await self._conn.commit()

    async def list_for_batch(
        self,
        batch_id: str,
        limit: int = 500,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        if status:
            cur = await self._conn.execute(
                "SELECT * FROM claims WHERE batch_id = ? AND status = ? LIMIT ?",
                (batch_id, status, limit),
            )
        else:
            cur = await self._conn.execute(
                "SELECT * FROM claims WHERE batch_id = ? LIMIT ?",
                (batch_id, limit),
            )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def list_all(
        self,
        limit: int = 500,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        if status:
            cur = await self._conn.execute(
                "SELECT * FROM claims WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            cur = await self._conn.execute(
                "SELECT * FROM claims ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_by_internal_id(self, internal_id: str) -> dict[str, Any] | None:
        cur = await self._conn.execute("SELECT * FROM claims WHERE id = ?", (internal_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_by_claim_id(self, claim_id: str) -> dict[str, Any] | None:
        cur = await self._conn.execute("SELECT * FROM claims WHERE claim_id = ?", (claim_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def update_status(self, internal_id: str, status: str) -> None:
        now = utc_now_iso()
        await self._conn.execute(
            "UPDATE claims SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, internal_id),
        )
        await self._conn.commit()


class WorkflowRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def create_run(self, batch_id: str, options: dict[str, Any]) -> str:
        rid = str(uuid.uuid4())
        now = utc_now_iso()
        await self._conn.execute(
            """
            INSERT INTO workflow_runs (id, batch_id, status, options_json, started_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (rid, batch_id, "running", json.dumps(options), now),
        )
        await self._conn.commit()
        return rid

    async def complete_run(self, run_id: str, status: str, error: str | None = None) -> None:
        now = utc_now_iso()
        await self._conn.execute(
            """
            UPDATE workflow_runs SET status = ?, completed_at = ?, error_message = ?
            WHERE id = ?
            """,
            (status, now, error, run_id),
        )
        await self._conn.commit()

    async def add_event(
        self,
        run_id: str,
        step: str,
        message: str,
        level: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> str:
        eid = str(uuid.uuid4())
        now = utc_now_iso()
        await self._conn.execute(
            """
            INSERT INTO workflow_events (id, run_id, step, level, message, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (eid, run_id, step, level, message, json.dumps(payload or {}), now),
        )
        await self._conn.commit()
        return eid

    async def list_recent_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        cur = await self._conn.execute(
            "SELECT * FROM workflow_runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def list_events(self, run_id: str, limit: int = 200) -> list[dict[str, Any]]:
        cur = await self._conn.execute(
            """
            SELECT * FROM workflow_events WHERE run_id = ?
            ORDER BY created_at ASC LIMIT ?
            """,
            (run_id, limit),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        cur = await self._conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


class AnalysisRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def save_classification(
        self,
        claim_internal_id: str,
        category: str,
        confidence: float,
        explanation: str,
        model_used: str,
    ) -> str:
        rid = str(uuid.uuid4())
        now = utc_now_iso()
        await self._conn.execute(
            """
            INSERT INTO classification_results
            (id, claim_internal_id, category, confidence, explanation, model_used, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (rid, claim_internal_id, category, confidence, explanation, model_used, now),
        )
        await self._conn.commit()
        return rid

    async def save_prioritization(
        self,
        claim_internal_id: str,
        priority_score: float,
        recoverable: float,
        urgency: float,
        reversal_probability: float,
        recommended_action: str,
        model_used: str,
    ) -> str:
        rid = str(uuid.uuid4())
        now = utc_now_iso()
        await self._conn.execute(
            """
            INSERT INTO prioritization_results
            (id, claim_internal_id, priority_score, estimated_recoverable_revenue,
             urgency, reversal_probability, recommended_action, model_used, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                claim_internal_id,
                priority_score,
                recoverable,
                urgency,
                reversal_probability,
                recommended_action,
                model_used,
                now,
            ),
        )
        await self._conn.commit()
        return rid

    async def save_rag(self, claim_internal_id: str, query: str, hits_json: str) -> str:
        rid = str(uuid.uuid4())
        now = utc_now_iso()
        await self._conn.execute(
            """
            INSERT INTO rag_retrievals (id, claim_internal_id, query, hits_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (rid, claim_internal_id, query, hits_json, now),
        )
        await self._conn.commit()
        return rid

    async def latest_classification(self, claim_internal_id: str) -> dict[str, Any] | None:
        cur = await self._conn.execute(
            """
            SELECT * FROM classification_results WHERE claim_internal_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (claim_internal_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def latest_prioritization(self, claim_internal_id: str) -> dict[str, Any] | None:
        cur = await self._conn.execute(
            """
            SELECT * FROM prioritization_results WHERE claim_internal_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (claim_internal_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


class AppealRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def create_draft(
        self,
        claim_internal_id: str,
        draft_text: str,
        citations_json: str,
        confidence: float,
        model_used: str,
        status: str = "awaiting_review",
    ) -> str:
        aid = str(uuid.uuid4())
        now = utc_now_iso()
        await self._conn.execute(
            """
            INSERT INTO appeals (
                id, claim_internal_id, status, draft_text, final_text, citations_json,
                confidence, model_used, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                aid,
                claim_internal_id,
                status,
                draft_text,
                None,
                citations_json,
                confidence,
                model_used,
                now,
                now,
            ),
        )
        await self._conn.commit()
        return aid

    async def get(self, appeal_id: str) -> dict[str, Any] | None:
        cur = await self._conn.execute("SELECT * FROM appeals WHERE id = ?", (appeal_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def list_awaiting(self, limit: int = 100) -> list[dict[str, Any]]:
        cur = await self._conn.execute(
            """
            SELECT * FROM appeals WHERE status = 'awaiting_review'
            ORDER BY updated_at DESC LIMIT ?
            """,
            (limit,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def approve(self, appeal_id: str) -> None:
        now = utc_now_iso()
        cur = await self._conn.execute("SELECT draft_text FROM appeals WHERE id = ?", (appeal_id,))
        row = await cur.fetchone()
        if not row:
            return
        draft = row[0]
        await self._conn.execute(
            """
            UPDATE appeals SET status = 'approved', final_text = ?, updated_at = ?
            WHERE id = ?
            """,
            (draft, now, appeal_id),
        )
        await self._conn.commit()

    async def reject(self, appeal_id: str) -> None:
        now = utc_now_iso()
        await self._conn.execute(
            "UPDATE appeals SET status = 'rejected', updated_at = ? WHERE id = ?",
            (now, appeal_id),
        )
        await self._conn.commit()

    async def edit(self, appeal_id: str, final_text: str) -> None:
        now = utc_now_iso()
        await self._conn.execute(
            """
            UPDATE appeals SET status = 'edited', final_text = ?, updated_at = ?
            WHERE id = ?
            """,
            (final_text, now, appeal_id),
        )
        await self._conn.commit()

    async def save_ai_review(
        self,
        appeal_id: str,
        review_json: str,
        model_used: str,
    ) -> None:
        now = utc_now_iso()
        await self._conn.execute(
            """
            UPDATE appeals
            SET ai_review_json = ?, ai_review_at = ?, ai_review_model = ?, updated_at = ?
            WHERE id = ?
            """,
            (review_json, now, model_used, now, appeal_id),
        )
        await self._conn.commit()

    async def latest_for_claim(self, claim_internal_id: str) -> dict[str, Any] | None:
        cur = await self._conn.execute(
            """
            SELECT * FROM appeals WHERE claim_internal_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (claim_internal_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


class AuditRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def append(
        self,
        entity_type: str,
        entity_id: str,
        actor: str,
        action: str,
        details: dict[str, Any],
    ) -> None:
        aid = str(uuid.uuid4())
        now = utc_now_iso()
        await self._conn.execute(
            """
            INSERT INTO audit_log (id, entity_type, entity_id, actor, action, details_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (aid, entity_type, entity_id, actor, action, json.dumps(details), now),
        )
        await self._conn.commit()

    async def list_for_entity(self, entity_type: str, entity_id: str, limit: int = 100) -> list[dict]:
        cur = await self._conn.execute(
            """
            SELECT * FROM audit_log WHERE entity_type = ? AND entity_id = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (entity_type, entity_id, limit),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
