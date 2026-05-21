from __future__ import annotations

import os

import httpx
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Upload — DenialFlow AI", layout="wide")


def base() -> str:
    return os.getenv("DENIALFLOW_API_BASE", "http://127.0.0.1:8000").rstrip("/")


st.title("Claims upload")
f = st.file_uploader("Upload denied claims CSV", type=["csv"])
if f is None:
    st.info("Upload a CSV with at least a `claim_id` column. See `data/sample_denials.csv`.")
    with st.expander("Colunas cadastrais (recomendadas para appeals)"):
        st.markdown(
            "Opcionais no schema, mas preencha para cartas sem placeholders `[Your Company Name]`:\n\n"
            "- **Prestador:** `provider_name`, `provider_address`, `provider_city`, "
            "`provider_state`, `provider_zip`, `signer_name`, `signer_title`, `provider_npi`\n"
            "- **Payer:** `payer` (nome) + `payer_address`, `payer_city`, `payer_state`, `payer_zip`\n"
            "- **Carta:** `letter_date` (se vazio, usa a data do workflow)"
        )
    st.stop()

raw = f.getvalue()
preview_lines = raw.decode("utf-8-sig", errors="replace").splitlines()[:15]
st.subheader("Preview (first 15 lines)")
st.code("\n".join(preview_lines), language="text")

if st.button("Validate + ingest", type="primary"):
    files = {"file": (f.name, raw, "text/csv")}
    try:
        r = httpx.post(f"{base()}/v1/claims/upload", files=files, timeout=60.0)
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
            wr = httpx.post(
                f"{base()}/v1/workflows/run",
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
