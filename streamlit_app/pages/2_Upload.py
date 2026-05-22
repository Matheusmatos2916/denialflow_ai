from __future__ import annotations

import pandas as pd
import streamlit as st

from api_client import api_request, render_auth_sidebar

st.set_page_config(page_title="Upload — DenialFlow AI", layout="wide")
render_auth_sidebar()

st.title("Claims upload")
f = st.file_uploader("Upload denied claims CSV", type=["csv"])
if f is None:
    st.info("Upload a CSV with at least a `claim_id` column. See `data/sample_denials.csv`.")
    with st.expander("Registration columns (recommended for appeals)"):
        st.markdown(
            "Optional in the schema, but fill in for letters without `[Your Company Name]` placeholders:\n\n"
            "- **Provider:** `provider_name`, `provider_address`, `provider_city`, "
            "`provider_state`, `provider_zip`, `signer_name`, `signer_title`, `provider_npi`\n"
            "- **Payer:** `payer` (name) + `payer_address`, `payer_city`, `payer_state`, `payer_zip`\n"
            "- **Letter:** `letter_date` (if empty, uses the workflow date)"
        )
    st.stop()

raw = f.getvalue()
preview_lines = raw.decode("utf-8-sig", errors="replace").splitlines()[:15]
st.subheader("Preview (first 15 lines)")
st.code("\n".join(preview_lines), language="text")

if st.button("Validate + ingest", type="primary"):
    files = {"file": (f.name, raw, "text/csv")}
    try:
        r = api_request("POST", "/v1/claims/upload", files=files, timeout=60.0)
        r.raise_for_status()
        resp = r.json()
    except Exception as e:  # noqa: BLE001
        st.error(str(e))
        st.stop()

    st.success(f"Batch created: `{resp['batch_id']}`")
    st.write(f"Accepted rows: **{resp['accepted_rows']}**")
    errs = resp.get("errors") or []
    if errs:
        st.warning(f"{len(errs)} validation issue(s) (non-blocking where partial accept).")
        st.dataframe(pd.DataFrame(errs), use_container_width=True, hide_index=True)
    st.session_state["last_batch_id"] = resp.get("batch_id")

bid = st.session_state.get("last_batch_id")
if bid:
    st.subheader("Run workflow on last batch")
    max_claims = st.slider("Max claims to process", 1, 50, 5)
    if st.button("Start workflow run", type="secondary"):
        try:
            wr = api_request(
                "POST",
                "/v1/workflows/run",
                json={"batch_id": bid, "max_claims": max_claims},
                timeout=30.0,
            )
            wr.raise_for_status()
            out = wr.json()
        except Exception as e:  # noqa: BLE001
            st.error(str(e))
            st.stop()
        st.success(f"Run started: `{out['run_id']}`")
        st.session_state["last_run_id"] = out["run_id"]
