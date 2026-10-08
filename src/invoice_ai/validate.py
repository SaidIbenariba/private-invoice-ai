"""Business-rule validation. Anything that fails a rule goes to a human; nothing is auto-approved on trust."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .schema import Invoice

REQUIRED = ["supplier_name", "invoice_number", "invoice_date", "currency", "total"]


@dataclass
class Rules:
    allowed_tax_rates: set[float] = field(default_factory=lambda: {0.0, 5.5, 7.0, 8.25, 10.0, 20.0})
    abs_tol: float = 0.02
    require_tax_id: bool = True


@dataclass
class Issue:
    code: str
    message: str


@dataclass
class Result:
    invoice: Invoice
    issues: list[Issue]

    @property
    def status(self) -> str:
        return "REVIEW" if self.issues else "APPROVED"


def _close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= max(tol, abs(b) * 1e-4)


def _parse(d: str | None) -> date | None:
    try:
        return date.fromisoformat(d) if d else None
    except ValueError:
        return None


def validate(inv: Invoice, rules: Rules | None = None) -> Result:
    rules = rules or Rules()
    issues: list[Issue] = []

    for name in REQUIRED:
        if getattr(inv, name) in (None, ""):
            issues.append(Issue("missing_field", f"{name} is missing"))

    if rules.require_tax_id and not inv.supplier_tax_id:
        issues.append(Issue("missing_tax_id", "supplier tax ID (VAT / ICE) not found"))

    issued, due = _parse(inv.invoice_date), _parse(inv.due_date)
    if inv.invoice_date and issued is None:
        issues.append(Issue("bad_date", f"invoice date '{inv.invoice_date}' is not a valid date"))
    if inv.due_date and due is None:
        issues.append(Issue("bad_date", f"due date '{inv.due_date}' is not a valid date"))
    if issued and due and due < issued:
        issues.append(Issue("due_before_issue", f"due date {due} is before invoice date {issued}"))

    for i, li in enumerate(inv.line_items, 1):
        if None not in (li.quantity, li.unit_price, li.amount):
            expected = round(li.quantity * li.unit_price, 2)
            if not _close(li.amount, expected, rules.abs_tol):
                issues.append(Issue(
                    "line_amount_mismatch",
                    f"line {i}: {li.quantity} x {li.unit_price} = {expected}, invoice says {li.amount}",
                ))

    amounts = [li.amount for li in inv.line_items]
    if inv.subtotal is not None and amounts and None not in amounts:
        s = round(sum(amounts), 2)
        if not _close(s, inv.subtotal, rules.abs_tol):
            issues.append(Issue("lines_sum_mismatch", f"line items sum to {s}, subtotal says {inv.subtotal}"))

    if inv.tax_rate is not None and inv.tax_rate not in rules.allowed_tax_rates:
        issues.append(Issue("tax_rate_not_allowed", f"tax rate {inv.tax_rate}% is not an expected rate"))

    if None not in (inv.subtotal, inv.tax_rate, inv.tax_amount):
        expected = round(inv.subtotal * inv.tax_rate / 100, 2)
        if not _close(inv.tax_amount, expected, rules.abs_tol):
            issues.append(Issue(
                "tax_mismatch", f"{inv.tax_rate}% of {inv.subtotal} = {expected}, invoice says {inv.tax_amount}",
            ))

    if None not in (inv.subtotal, inv.tax_amount, inv.total):
        expected = round(inv.subtotal + inv.tax_amount, 2)
        if not _close(inv.total, expected, rules.abs_tol):
            issues.append(Issue("total_mismatch", f"subtotal + tax = {expected}, total says {inv.total}"))

    return Result(inv, issues)


def _dup_key(inv: Invoice) -> tuple[str, str] | None:
    if not inv.invoice_number or not inv.supplier_name:
        return None
    norm = lambda s: "".join(s.lower().split())
    return norm(inv.supplier_name), norm(inv.invoice_number)


def validate_batch(invoices: list[Invoice], rules: Rules | None = None) -> list[Result]:
    seen: set[tuple[str, str]] = set()
    results = []
    for inv in invoices:
        r = validate(inv, rules)
        key = _dup_key(inv)
        if key and key in seen:
            r.issues.append(Issue("duplicate", f"invoice {inv.invoice_number} from {inv.supplier_name} already processed"))
        if key:
            seen.add(key)
        results.append(r)
    return results
