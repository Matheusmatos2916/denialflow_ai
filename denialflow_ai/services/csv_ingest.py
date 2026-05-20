from __future__ import annotations

import csv
import io
import json
from typing import Any

from denialflow_ai.schemas import ClaimRow, ParsedCsv, UploadValidationError


def parse_claims_csv(content: bytes, filename: str) -> ParsedCsv:
    """Validate CSV rows and return structured errors for invalid lines."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    required = {"claim_id"}
    fieldnames = reader.fieldnames or []
    missing = [c for c in required if c not in fieldnames]
    if missing:
        return ParsedCsv(
            filename=filename,
            rows=[],
            errors=[
                UploadValidationError(row_index=0, field=None, message=f"Missing columns: {missing}")
            ],
        )

    accepted: list[dict[str, Any]] = []
    errors: list[UploadValidationError] = []
    for idx, row in enumerate(reader, start=2):  # header is line 1
        try:
            cr = ClaimRow.model_validate(
                {
                    "claim_id": (row.get("claim_id") or "").strip(),
                    "payer": row.get("payer") or "",
                    "denial_code": row.get("denial_code") or "",
                    "denial_reason_text": row.get("denial_reason_text") or "",
                    "billed_amount": float(row.get("billed_amount") or 0),
                    "allowed_amount": float(row.get("allowed_amount") or 0),
                    "patient_balance": float(row.get("patient_balance") or 0),
                    "aging_days": int(float(row.get("aging_days") or 0)),
                    "specialty": row.get("specialty") or "",
                    "cpt_codes": row.get("cpt_codes") or "",
                    "icd10_codes": row.get("icd10_codes") or "",
                    "service_date": row.get("service_date") or "",
                    "remark_codes": row.get("remark_codes") or "",
                }
            )
        except Exception as e:  # noqa: BLE001
            errors.append(
                UploadValidationError(row_index=idx, field=None, message=str(e)),
            )
            continue
        accepted.append({**cr.model_dump(), "raw": cr.model_dump()})

    return ParsedCsv(filename=filename, rows=accepted, errors=errors)
