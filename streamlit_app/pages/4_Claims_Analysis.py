from __future__ import annotations

import os

import httpx
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Claims analysis — DenialFlow AI", layout="wide")


def base() -> str:
    return os.getenv("DENIALFLOW_API_BASE", "http://127.0.0.1:8000").rstrip("/")


st.title("Claims analysis")
status = st.selectbox(
    "Filter status",
    options=["(summary)", "pending", "awaiting_review", "approved", "rejected", "edited"],
)

try:
    if status == "(summary)":
        r = httpx.get(f"{base()}/v1/claims/summary", params={"limit": 500}, timeout=30.0)
        r.raise_for_status()
        rows = r.json().get("items", [])
    else:
        r = httpx.get(f"{base()}/v1/claims", params={"limit": 500, "status": status}, timeout=30.0)
        r.raise_for_status()
        raw_rows = r.json().get("items", [])
        rows = [
            {
                "internal_id": x.get("id"),
                "claim_id": x.get("claim_id"),
                "payer": x.get("payer"),
                "denial_reason": x.get("denial_reason_text"),
                "status": x.get("status"),
            }
            for x in raw_rows
        ]
except Exception as e:  # noqa: BLE001
    st.error(str(e))
    st.stop()

st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

if status == "(summary)":
    st.caption("Showing joined summary (AI classification + prioritization when available).")
