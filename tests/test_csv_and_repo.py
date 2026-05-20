import pytest

from denialflow_ai.repositories import BatchRepository, ClaimRepository
from denialflow_ai.services.csv_ingest import parse_claims_csv


def test_parse_claims_csv_ok():
    csv_text = "claim_id,payer,denial_code,billed_amount\nCLM-1,Horizon,CO-50,123.45\n"
    parsed = parse_claims_csv(csv_text.encode("utf-8"), "t.csv")
    assert len(parsed.rows) == 1
    assert parsed.rows[0]["claim_id"] == "CLM-1"
    assert not parsed.errors


def test_parse_claims_csv_bad_number():
    csv_text = "claim_id,payer,denial_code,billed_amount\nCLM-1,Horizon,CO-50,not_a_float\n"
    parsed = parse_claims_csv(csv_text.encode("utf-8"), "t.csv")
    assert len(parsed.rows) == 0
    assert parsed.errors


def test_batch_repo(tmp_path):
    import asyncio

    asyncio.run(_batch_repo(tmp_path))


async def _batch_repo(tmp_path):
    db_path = tmp_path / "t.db"
    import aiosqlite

    from denialflow_ai.db import init_db

    await init_db(str(db_path))
    conn = await aiosqlite.connect(str(db_path))
    conn.row_factory = aiosqlite.Row
    br = BatchRepository(conn)
    bid = await br.create("f.csv", 2)
    cr = ClaimRepository(conn)
    await cr.insert_many(
        bid,
        [
            {
                "claim_id": "A1",
                "payer": "P",
                "denial_code": "CO-50",
                "denial_reason_text": "x",
                "billed_amount": 1.0,
                "allowed_amount": 0.0,
                "patient_balance": 0.0,
                "aging_days": 1,
                "specialty": "s",
                "cpt_codes": "",
                "icd10_codes": "",
                "service_date": "",
                "remark_codes": "",
                "raw": {"claim_id": "A1"},
            }
        ],
    )
    rows = await cr.list_for_batch(bid)
    assert len(rows) == 1
    await conn.close()
