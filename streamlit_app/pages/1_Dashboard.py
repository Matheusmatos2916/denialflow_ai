from __future__ import annotations

import pandas as pd
import streamlit as st

from api_client import api_request, render_auth_sidebar

st.set_page_config(page_title="Dashboard — DenialFlow AI", layout="wide")
render_auth_sidebar()

st.title("Operational dashboard")
st.caption("Aggregated metrics from the DenialFlow API + lightweight ops counters")

try:
    r = api_request("GET", "/v1/metrics/dashboard", timeout=10.0)
    r.raise_for_status()
    m = r.json()
except Exception as e:  # noqa: BLE001
    st.error(f"Failed to load metrics: {e}")
    st.stop()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total claims", f"{m.get('total_claims', 0):,}")
c2.metric("Denial rate (proxy)", f"{m.get('denial_rate_proxy', 0.0) * 100:.1f}%")
c3.metric("Recoverable revenue (sum est.)", f"${m.get('recoverable_revenue_sum', 0.0):,.0f}")
c4.metric("Awaiting review", f"{m.get('awaiting_review', 0):,}")
avg = m.get("avg_run_duration_ms")
c5.metric("Avg run duration", f"{avg:,.0f} ms" if avg is not None else "n/a")

st.subheader("Runs (24h window)")
st.write(f"{m.get('runs_last_24h', 0)} workflow runs started in the last day (date-based heuristic).")

st.subheader("Priority queue (top 10)")
pq = m.get("priority_queue_top") or []
if pq:
    st.dataframe(pd.DataFrame(pq), use_container_width=True, hide_index=True)
else:
    st.info("No prioritization rows yet — upload claims and run a workflow.")

try:
    ops = api_request("GET", "/v1/metrics/ops", timeout=5.0).json()
    with st.expander("Ops snapshot (process-local)"):
        st.json(ops)
except Exception:
    pass
