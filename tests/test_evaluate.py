from invoice_ai.evaluate import DocOutcome, compare, summarize
from invoice_ai.schema import Invoice, LineItem


def inv(**kw):
    base = dict(supplier_name="Atlas Transport SARL", supplier_tax_id="123", invoice_number="2026/1",
                invoice_date="2026-09-01", due_date="2026-10-01", currency="MAD", subtotal=100.0,
                tax_rate=20.0, tax_amount=20.0, total=120.0,
                line_items=[LineItem(description="A", quantity=2, unit_price=50, amount=100)])
    base.update(kw)
    return Invoice(**base)


def test_identical_is_fully_correct():
    c = compare(inv(), inv())
    assert c.fully_correct
    assert all(c.fields.values())


def test_supplier_name_case_and_punctuation_insensitive():
    c = compare(inv(supplier_name="ATLAS TRANSPORT SARL."), inv())
    assert c.fields["supplier_name"]


def test_number_tolerance():
    assert compare(inv(total=120.004), inv()).fields["total"]
    assert not compare(inv(total=121.0), inv()).fields["total"]


def test_wrong_line_item_breaks_full_correctness():
    pred = inv(line_items=[LineItem(description="A", quantity=50, unit_price=2, amount=100)])
    c = compare(pred, inv())
    assert all(c.fields.values())
    assert not c.lines_correct
    assert not c.fully_correct


def test_missing_line_counts_as_wrong():
    assert not compare(inv(line_items=[]), inv()).lines_correct


def outcome(status, correct, anomaly):
    return DocOutcome(doc_id="x", status=status, fully_correct=correct, anomaly=anomaly,
                      fields={"total": correct}, lines_correct=correct, seconds=1.0, route="text")


def test_summary_metrics():
    docs = [
        outcome("APPROVED", True, None),          # correct auto-approval
        outcome("APPROVED", False, None),         # bad auto-approval (extraction error slipped through)
        outcome("REVIEW", True, "total_mismatch"),  # anomaly caught
        outcome("APPROVED", True, "duplicate"),   # anomaly missed
        outcome("REVIEW", False, None),           # extraction error caught
    ]
    s = summarize(docs)
    assert s["documents"] == 5
    assert s["auto_approved"] == 3
    assert s["auto_approve_precision"] == 1 / 3   # only the first is truly safe
    assert s["anomalies_caught"] == 1 and s["anomalies_total"] == 2
    assert s["errors_reaching_approval"] == 2
