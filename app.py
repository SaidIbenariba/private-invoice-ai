"""Review screen. Run: uv run streamlit run app.py"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from invoice_ai.extract import DEFAULT_MODEL, load_page
from invoice_ai.pipeline import run

ROOT = Path(__file__).parent
SAMPLES = ROOT / "data" / "samples"
OUT = ROOT / "out"

st.set_page_config(page_title="Private Invoice AI", layout="wide")
st.markdown("""
<style>
.block-container {padding-top: 1.6rem;}
.pill {display:inline-block;padding:2px 10px;border-radius:12px;font-weight:600;font-size:0.85rem}
.ok {background:#dcf5e3;color:#17703a} .flag {background:#fde2e1;color:#b42318}
.issue {background:#fff4f2;border-left:4px solid #d93025;padding:6px 10px;margin:4px 0;border-radius:4px}
</style>""", unsafe_allow_html=True)

st.title("Private Invoice AI")
st.caption("Invoices, scans and phone photos to validated data. Runs 100% locally with Ollama: "
           "no document is sent to OpenAI or any cloud API.")

with st.sidebar:
    st.subheader("Batch")
    source = st.radio("Documents", ["Sample batch (24 invoices)", "Upload my own"], label_visibility="collapsed")
    uploads = None
    if source == "Upload my own":
        uploads = st.file_uploader("PDF, JPG or PNG", type=["pdf", "jpg", "jpeg", "png"], accept_multiple_files=True)
    model = st.text_input("Local model", DEFAULT_MODEL)
    go = st.button("Process", type="primary", use_container_width=True)
    st.divider()
    st.markdown("**Checks applied**\n- required fields\n- qty x price = line amount\n- lines sum = subtotal\n"
                "- tax = subtotal x rate\n- subtotal + tax = total\n- allowed tax rates\n- due date after invoice date\n"
                "- supplier tax ID present\n- duplicate invoice in batch")

if source == "Upload my own":
    in_dir, out_dir, truth = OUT / "uploads", OUT / "uploads_run", None
else:
    in_dir, out_dir, truth = SAMPLES, OUT, SAMPLES / "truth"

if go:
    if uploads:
        in_dir.mkdir(parents=True, exist_ok=True)
        for f in uploads:
            (in_dir / f.name).write_bytes(f.getvalue())
    with st.status("Processing locally...", expanded=True) as s:
        report = run(in_dir, out_dir, truth, model=model, log=s.write)
        s.update(label="Done", state="complete")
    st.session_state["report"] = report
elif "report" not in st.session_state and (out_dir / "report.json").exists():
    st.session_state["report"] = json.loads((out_dir / "report.json").read_text())

report = st.session_state.get("report")
if not report:
    st.info("Choose a batch and press Process.")
    st.stop()

docs = report["documents"]
summary = report.get("summary")
n = len(docs)
approved = sum(d["status"] == "APPROVED" for d in docs)

k = st.columns(5)
k[0].metric("Documents", n)
k[1].metric("Auto-approved", approved)
k[2].metric("Sent to review", n - approved)
if summary:
    k[3].metric("Auto-approve precision", f"{summary['auto_approve_precision']:.0%}")
    k[4].metric("Planted errors caught", f"{summary['anomalies_caught']}/{summary['anomalies_total']}")

table = pd.DataFrame([{
    "File": d["file"], "Status": d["status"], "Supplier": d["invoice"]["supplier_name"],
    "Invoice no": d["invoice"]["invoice_number"], "Date": d["invoice"]["invoice_date"],
    "Currency": d["invoice"]["currency"], "Total": d["invoice"]["total"],
    "Issues": len(d["issues"]), "Read via": d["route"],
} for d in docs])


def color_status(v):
    return "background-color:#dcf5e3;color:#17703a" if v == "APPROVED" else "background-color:#fde2e1;color:#b42318"


st.dataframe(table.style.map(color_status, subset=["Status"]).format({"Total": "{:,.2f}"}),
             use_container_width=True, hide_index=True, height=300)

xlsx = out_dir / "invoices.xlsx"
if xlsx.exists():
    st.download_button("Download Excel", xlsx.read_bytes(), "invoices.xlsx", use_container_width=False)

st.divider()
st.subheader("Review")
review_first = sorted(docs, key=lambda d: d["status"] == "APPROVED")
pick = st.selectbox("Document", [d["file"] for d in review_first],
                    format_func=lambda f: f"{f}  ·  {next(d['status'] for d in docs if d['file'] == f)}")
doc = next(d for d in docs if d["file"] == pick)
inv = doc["invoice"]

left, right = st.columns([1, 1])
with left:
    img, _ = load_page(in_dir / doc["file"])
    st.image(img, use_container_width=True)
with right:
    cls = "ok" if doc["status"] == "APPROVED" else "flag"
    st.markdown(f'<span class="pill {cls}">{doc["status"]}</span> &nbsp; read via **{doc["route"]}** path '
                f'in {doc["seconds"]:.0f}s', unsafe_allow_html=True)
    for i in doc["issues"]:
        st.markdown(f'<div class="issue">{i["message"]}</div>', unsafe_allow_html=True)
    fields = pd.DataFrame(
        [(k_, v) for k_, v in inv.items() if k_ != "line_items"], columns=["Field", "Value"]).astype({"Value": str})
    st.data_editor(fields, hide_index=True, use_container_width=True, disabled=["Field"], key=f"f_{pick}")
    st.data_editor(pd.DataFrame(inv["line_items"]), hide_index=True, use_container_width=True, key=f"l_{pick}")
    c1, c2 = st.columns(2)
    if c1.button("Confirm", type="primary", use_container_width=True, key=f"ok_{pick}"):
        st.success("Confirmed. In production this writes to your database or ERP.")
    c2.button("Reject", use_container_width=True, key=f"no_{pick}")
    if "wrong_fields" in doc:
        wrong = doc["wrong_fields"]
        st.caption("Ground truth check: " + ("all fields correct" if not wrong else "wrong: " + ", ".join(wrong))
                   + (f" · planted error: {doc['anomaly']}" if doc.get("anomaly") else ""))
