from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from api_client import api_request, render_auth_sidebar

st.set_page_config(page_title="Workflow — DenialFlow AI", layout="wide")
render_auth_sidebar()

st.title("Processing workflow")
st.caption("Live-ish view of workflow runs and structured agent logs")

rid = st.text_input("Run ID", value=st.session_state.get("last_run_id", ""))
auto = st.toggle("Auto-refresh (5s)", value=False)

if not rid:
    st.info("Paste a run id from Upload, or query recent runs below.")
else:
    col1, col2 = st.columns([1, 2])
    with col1:
        try:
            run = api_request("GET", f"/v1/workflows/{rid}", timeout=10.0).json()
            st.json(run)
        except Exception as e:  # noqa: BLE001
            st.error(str(e))
    with col2:
        try:
            ev = api_request("GET", f"/v1/workflows/{rid}/events", timeout=10.0).json().get(
                "items", []
            )
            st.dataframe(pd.DataFrame(ev), use_container_width=True, hide_index=True)
        except Exception as e:  # noqa: BLE001
            st.error(str(e))

st.subheader("Recent runs")
try:
    runs = api_request("GET", "/v1/workflows", timeout=10.0).json().get("items", [])
    st.dataframe(pd.DataFrame(runs), use_container_width=True, hide_index=True)
except Exception as e:  # noqa: BLE001
    st.error(str(e))

if auto:
    time.sleep(5)
    st.rerun()
