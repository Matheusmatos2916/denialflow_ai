"""SQLite bootstrap and schema for DenialFlow AI."""

from __future__ import annotations

import aiosqlite

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'uploaded'
);

CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES batches(id),
    claim_id TEXT NOT NULL,
    payer TEXT,
    denial_code TEXT,
    denial_reason_text TEXT,
    billed_amount REAL,
    allowed_amount REAL,
    patient_balance REAL,
    aging_days INTEGER,
    specialty TEXT,
    cpt_codes TEXT,
    icd10_codes TEXT,
    service_date TEXT,
    remark_codes TEXT,
    raw_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(batch_id, claim_id)
);

CREATE INDEX IF NOT EXISTS idx_claims_batch ON claims(batch_id);
CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES batches(id),
    status TEXT NOT NULL DEFAULT 'running',
    options_json TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS workflow_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES workflow_runs(id),
    step TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    payload_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_run ON workflow_events(run_id);

CREATE TABLE IF NOT EXISTS classification_results (
    id TEXT PRIMARY KEY,
    claim_internal_id TEXT NOT NULL REFERENCES claims(id),
    category TEXT NOT NULL,
    confidence REAL NOT NULL,
    explanation TEXT NOT NULL,
    model_used TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prioritization_results (
    id TEXT PRIMARY KEY,
    claim_internal_id TEXT NOT NULL REFERENCES claims(id),
    priority_score REAL NOT NULL,
    estimated_recoverable_revenue REAL NOT NULL,
    urgency REAL NOT NULL,
    reversal_probability REAL NOT NULL,
    recommended_action TEXT NOT NULL,
    model_used TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rag_retrievals (
    id TEXT PRIMARY KEY,
    claim_internal_id TEXT NOT NULL REFERENCES claims(id),
    query TEXT NOT NULL,
    hits_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS appeals (
    id TEXT PRIMARY KEY,
    claim_internal_id TEXT NOT NULL REFERENCES claims(id),
    status TEXT NOT NULL DEFAULT 'draft',
    draft_text TEXT NOT NULL,
    final_text TEXT,
    citations_json TEXT NOT NULL,
    confidence REAL NOT NULL,
    model_used TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_appeals_status ON appeals(status);

CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);
"""


_CLAIMS_COLUMNS = """
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES batches(id),
    claim_id TEXT NOT NULL,
    payer TEXT,
    denial_code TEXT,
    denial_reason_text TEXT,
    billed_amount REAL,
    allowed_amount REAL,
    patient_balance REAL,
    aging_days INTEGER,
    specialty TEXT,
    cpt_codes TEXT,
    icd10_codes TEXT,
    service_date TEXT,
    remark_codes TEXT,
    raw_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(batch_id, claim_id)
"""


async def _migrate_claims_batch_unique(db: aiosqlite.Connection) -> None:
    """Allow the same payer claim_id in different upload batches (demo re-uploads)."""
    cur = await db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='claims'"
    )
    row = await cur.fetchone()
    if not row or not row[0]:
        return
    ddl = str(row[0])
    if "UNIQUE(batch_id, claim_id)" in ddl.replace("\n", " "):
        return
    if "claim_id TEXT NOT NULL UNIQUE" not in ddl:
        return
    await db.execute(f"CREATE TABLE claims_new ({_CLAIMS_COLUMNS})")
    await db.execute("INSERT INTO claims_new SELECT * FROM claims")
    await db.execute("DROP TABLE claims")
    await db.execute("ALTER TABLE claims_new RENAME TO claims")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_claims_batch ON claims(batch_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status)")


async def init_db(db_path: str) -> None:
    """Create tables if they do not exist."""
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(SCHEMA)
        await _migrate_claims_batch_unique(db)
        await db.commit()
