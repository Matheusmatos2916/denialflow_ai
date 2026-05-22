from __future__ import annotations

import pandas as pd
import streamlit as st

from api_client import api_request, render_auth_sidebar

st.set_page_config(page_title="Claims analysis — DenialFlow AI", layout="wide")
render_auth_sidebar()

st.title("Claims analysis")
status = st.selectbox(
    "Filter status",
    options=["(summary)", "pending", "awaiting_review", "approved", "rejected", "edited"],
)

try:
    if status == "(summary)":
        r = api_request("GET", "/v1/claims/summary", params={"limit": 500}, timeout=30.0)
        r.raise_for_status()
        rows = r.json().get("items", [])
    else:
        r = api_request(
            "GET", "/v1/claims", params={"limit": 500, "status": status}, timeout=30.0
        )
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
