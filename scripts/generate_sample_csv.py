"""
Generate a realistic synthetic CSV of denied claims for demos.
Run: python scripts/generate_sample_csv.py
"""

from __future__ import annotations

import csv
import random
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
OUT = ROOT / "data" / "sample_denials.csv"

PAYERS = [
    "Horizon National",
    "Apex Health Plan",
    "UnifiedCare",
    "Meridian Select",
    "Lakeside Medicare Advantage",
]

SPECIALTIES = [
    "Orthopedic Surgery",
    "Emergency Medicine",
    "Radiology",
    "Cardiology",
    "Internal Medicine",
    "Gastroenterology",
]

DENIAL_TEMPLATES = [
    ("CO-50", "These services are not medically necessary based on payer guidelines."),
    ("CO-97", "The benefit for this service is included in the payment/allowance for another service."),
    ("CO-16", "Claim/service lacks information which is needed for adjudication."),
    ("CO-18", "Duplicate claim/service."),
    ("CO-15", "The authorization number is missing, incomplete, or invalid."),
    ("CO-252", "An attachment/other documentation is required to adjudicate this claim/service."),
    ("PR-96", "Non-covered charge(s) (documentation does not support coded service)."),
]

CPT_POOL = ["99285", "73721", "78452", "45380", "27447", "92928", "J0897", "77067"]
ICD_POOL = ["M17.11", "I25.10", "K63.5", "R07.89", "S72.001A", "Z87.891"]


def main() -> None:
    random.seed(42)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = 320
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "claim_id",
                "payer",
                "denial_code",
                "denial_reason_text",
                "billed_amount",
                "allowed_amount",
                "patient_balance",
                "aging_days",
                "specialty",
                "cpt_codes",
                "icd10_codes",
                "service_date",
                "remark_codes",
            ],
        )
        w.writeheader()
        for i in range(rows):
            payer = random.choice(PAYERS)
            code, reason = random.choice(DENIAL_TEMPLATES)
            billed = round(random.uniform(800, 185_000), 2)
            allowed = round(billed * random.uniform(0.0, 0.85), 2)
            patient_bal = round(max(0.0, billed - allowed) * random.uniform(0.0, 0.35), 2)
            aging = random.randint(3, 120)
            spec = random.choice(SPECIALTIES)
            cpts = ",".join(random.sample(CPT_POOL, k=random.randint(1, 3)))
            icds = ",".join(random.sample(ICD_POOL, k=random.randint(1, 2)))
            dos = f"2025-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"
            remark = random.choice(["", "MA15", "N382", "M86"])
            w.writerow(
                {
                    "claim_id": f"CLM-DF-{2025000 + i}",
                    "payer": payer,
                    "denial_code": code,
                    "denial_reason_text": reason,
                    "billed_amount": billed,
                    "allowed_amount": allowed,
                    "patient_balance": patient_bal,
                    "aging_days": aging,
                    "specialty": spec,
                    "cpt_codes": cpts,
                    "icd10_codes": icds,
                    "service_date": dos,
                    "remark_codes": remark,
                }
            )
    print(f"Wrote {rows} rows to {OUT}")


if __name__ == "__main__":
    main()
