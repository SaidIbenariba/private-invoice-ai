"""CLI.

    python -m invoice_ai generate [data/samples]          # synthetic invoices + ground truth
    python -m invoice_ai run data/samples --out out       # extract, validate, export Excel
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .extract import DEFAULT_MODEL
from .pipeline import run
from .synth import generate


def main() -> None:
    p = argparse.ArgumentParser(prog="invoice_ai")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("out", nargs="?", default="data/samples")
    g.add_argument("-n", type=int, default=24)
    g.add_argument("--seed", type=int, default=7)
    r = sub.add_parser("run")
    r.add_argument("input")
    r.add_argument("--out", default="out")
    r.add_argument("--truth", default=None, help="ground-truth dir (default: <input>/truth if present)")
    r.add_argument("--model", default=DEFAULT_MODEL)
    a = p.parse_args()

    if a.cmd == "generate":
        generate(Path(a.out), n=a.n, seed=a.seed)
        print(f"wrote {a.n} invoices to {a.out}")
        return

    inp = Path(a.input)
    truth = Path(a.truth) if a.truth else inp / "truth"
    report = run(inp, Path(a.out), truth if truth.exists() else None, model=a.model)
    s = report["summary"]
    n = len(report["documents"])
    approved = sum(d["status"] == "APPROVED" for d in report["documents"])
    print(f"\n{n} documents: {approved} auto-approved, {n - approved} sent to review")
    if s:
        print(json.dumps({k: v for k, v in s.items() if k != "field_accuracy"}, indent=2))
    print(f"Excel: {Path(a.out) / 'invoices.xlsx'}")


if __name__ == "__main__":
    main()
