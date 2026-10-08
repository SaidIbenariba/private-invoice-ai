"""Measure extraction and routing quality against ground truth.

The number that matters for a finance team: of the invoices the system auto-approves, how many
were actually right? Everything else is reviewed by a human anyway.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import HEADER_FIELDS, NUMERIC_FIELDS, Invoice, LineItem

TOL = 0.011


def _norm(s: str | None) -> str:
    return re.sub(r"[^0-9a-z]", "", (s or "").lower())


def _num_eq(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a - b) <= TOL


def _field_eq(name: str, a, b) -> bool:
    if name in NUMERIC_FIELDS:
        return _num_eq(a, b)
    return _norm(a) == _norm(b)


def _line_eq(a: LineItem, b: LineItem) -> bool:
    return _num_eq(a.quantity, b.quantity) and _num_eq(a.unit_price, b.unit_price) and _num_eq(a.amount, b.amount)


@dataclass
class Comparison:
    fields: dict[str, bool]
    lines_correct: bool

    @property
    def fully_correct(self) -> bool:
        return all(self.fields.values()) and self.lines_correct


def compare(pred: Invoice, truth: Invoice) -> Comparison:
    fields = {f: _field_eq(f, getattr(pred, f), getattr(truth, f)) for f in HEADER_FIELDS}
    lines = len(pred.line_items) == len(truth.line_items) and all(
        _line_eq(p, t) for p, t in zip(pred.line_items, truth.line_items))
    return Comparison(fields, lines)


@dataclass
class DocOutcome:
    doc_id: str
    status: str
    fully_correct: bool
    anomaly: str | None
    fields: dict[str, bool]
    lines_correct: bool
    seconds: float
    route: str

    @property
    def safe_to_approve(self) -> bool:
        return self.fully_correct and self.anomaly is None


def summarize(docs: list[DocOutcome]) -> dict:
    n = len(docs)
    approved = [d for d in docs if d.status == "APPROVED"]
    anomalies = [d for d in docs if d.anomaly]
    field_names = list(docs[0].fields) if docs else []
    return {
        "documents": n,
        "auto_approved": len(approved),
        "auto_approval_rate": len(approved) / n if n else 0.0,
        "auto_approve_precision": (sum(d.safe_to_approve for d in approved) / len(approved)) if approved else 1.0,
        "errors_reaching_approval": sum(not d.safe_to_approve for d in approved),
        "anomalies_total": len(anomalies),
        "anomalies_caught": sum(d.status == "REVIEW" for d in anomalies),
        "fully_correct_extractions": sum(d.fully_correct for d in docs),
        "line_items_correct": sum(d.lines_correct for d in docs),
        "field_accuracy": {f: sum(d.fields[f] for d in docs) / n for f in field_names},
        "header_field_accuracy": (sum(sum(d.fields.values()) for d in docs) / (n * len(field_names))) if n else 0.0,
        "avg_seconds": {r: round(sum(d.seconds for d in docs if d.route == r) / max(1, sum(d.route == r for d in docs)), 1)
                        for r in ("text", "vision")},
    }
