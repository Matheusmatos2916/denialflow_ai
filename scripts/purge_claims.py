"""Remove all claims and related workflow/AI data from denialflow.db."""
from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "denialflow.db"

TABLES_CHILD_FIRST = [
    "workflow_events",
    "workflow_runs",
    "appeals",
    "classification_results",
    "prioritization_results",
    "rag_retrievals",
    "claims",
    "batches",
]


def main() -> None:
    if not DB.exists():
        raise SystemExit(f"Database not found: {DB}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = DB.with_suffix(f".db.bak-{stamp}")
    shutil.copy2(DB, backup)
    print(f"Backup: {backup}")

    conn = sqlite3.connect(DB)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        before = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in TABLES_CHILD_FIRST
        }
        print("Before:", before)

        for table in TABLES_CHILD_FIRST:
            conn.execute(f"DELETE FROM {table}")

        # Optional: clear audit rows tied to removed entities
        conn.execute(
            "DELETE FROM audit_log WHERE entity_type IN ('claim', 'batch', 'appeal', 'workflow_run')"
        )

        conn.commit()

        after = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in TABLES_CHILD_FIRST
        }
        audit = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        print("After:", after)
        print(f"audit_log remaining rows: {audit}")
    finally:
        conn.close()

    print("Done. Upload a new CSV to repopulate claims.")


if __name__ == "__main__":
    main()
