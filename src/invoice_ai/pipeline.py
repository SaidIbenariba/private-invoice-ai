"""Batch run: extract (cached) -> validate -> evaluate (if truth exists) -> Excel + JSON report."""

from __future__ import annotations

import json
from pathlib import Path

from .evaluate import DocOutcome, compare, summarize
from .export import write_workbook
from .extract import DEFAULT_MODEL, extract
from .normalize import to_invoice
from .schema import Invoice
from .validate import Rules, validate_batch

DOC_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png"}


def list_docs(input_dir: Path) -> list[Path]:
    return sorted(p for p in input_dir.iterdir() if p.suffix.lower() in DOC_SUFFIXES)


def extract_cached(doc: Path, cache_dir: Path, model: str = DEFAULT_MODEL, log=print) -> dict:
    cache = cache_dir / f"{doc.stem}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    e = extract(doc, model)
    rec = {"file": doc.name, "route": e.path, "seconds": round(e.seconds, 1), "raw": e.raw}
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    log(f"  {doc.name}: {e.path} path, {e.seconds:.0f}s")
    return rec


def run(input_dir: Path, out_dir: Path, truth_dir: Path | None = None, rules: Rules | None = None,
        model: str = DEFAULT_MODEL, log=print) -> dict:
    docs = list_docs(input_dir)
    log(f"{len(docs)} documents in {input_dir}")
    recs = [extract_cached(d, out_dir / "extractions", model, log) for d in docs]
    invoices = [to_invoice(r["raw"]) for r in recs]
    results = validate_batch(invoices, rules)

    summary = None
    outcomes = []
    if truth_dir and truth_dir.exists():
        for d, r, rec in zip(docs, results, recs):
            t = json.loads((truth_dir / f"{d.stem}.json").read_text())
            c = compare(r.invoice, Invoice.model_validate(t["invoice"]))
            outcomes.append(DocOutcome(d.stem, r.status, c.fully_correct, t["anomaly"], c.fields,
                                       c.lines_correct, rec["seconds"], rec["route"]))
        summary = summarize(outcomes)

    write_workbook(out_dir / "invoices.xlsx", [d.name for d in docs], results, recs, summary)
    report = {
        "summary": summary,
        "documents": [
            {"file": d.name, "status": r.status, "route": rec["route"], "seconds": rec["seconds"],
             "issues": [{"code": i.code, "message": i.message} for i in r.issues],
             "invoice": r.invoice.model_dump(),
             **({"fully_correct": o.fully_correct, "anomaly": o.anomaly,
                 "wrong_fields": [k for k, v in o.fields.items() if not v] + ([] if o.lines_correct else ["line_items"])}
                if outcomes else {})}
            for d, r, rec, o in zip(docs, results, recs, outcomes or [None] * len(docs))
        ],
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return report
