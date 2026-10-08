from invoice_ai.schema import Invoice, LineItem
from invoice_ai.validate import Rules, validate, validate_batch


def good_invoice(**overrides) -> Invoice:
    data = dict(
        supplier_name="Atlas Office Supply",
        supplier_tax_id="FR12345678901",
        invoice_number="INV-1001",
        invoice_date="2026-09-01",
        due_date="2026-10-01",
        currency="EUR",
        subtotal=150.0,
        tax_rate=20.0,
        tax_amount=30.0,
        total=180.0,
        line_items=[
            LineItem(description="Paper", quantity=10, unit_price=5.0, amount=50.0),
            LineItem(description="Toner", quantity=2, unit_price=50.0, amount=100.0),
        ],
    )
    data.update(overrides)
    return Invoice(**data)


def codes(result):
    return {i.code for i in result.issues}


def test_clean_invoice_is_approved():
    r = validate(good_invoice())
    assert r.status == "APPROVED"
    assert r.issues == []


def test_missing_required_field_goes_to_review():
    r = validate(good_invoice(invoice_number=None))
    assert r.status == "REVIEW"
    assert "missing_field" in codes(r)


def test_total_not_equal_subtotal_plus_tax():
    r = validate(good_invoice(total=190.0))
    assert "total_mismatch" in codes(r)


def test_tax_not_matching_rate():
    r = validate(good_invoice(tax_amount=25.0, total=175.0))
    assert "tax_mismatch" in codes(r)


def test_line_amount_not_qty_times_price():
    items = [
        LineItem(description="Paper", quantity=10, unit_price=5.0, amount=60.0),
        LineItem(description="Toner", quantity=2, unit_price=50.0, amount=90.0),
    ]
    r = validate(good_invoice(line_items=items))
    assert "line_amount_mismatch" in codes(r)


def test_lines_do_not_sum_to_subtotal():
    r = validate(good_invoice(subtotal=160.0, tax_amount=32.0, total=192.0))
    assert "lines_sum_mismatch" in codes(r)


def test_due_date_before_invoice_date():
    r = validate(good_invoice(due_date="2026-08-01"))
    assert "due_before_issue" in codes(r)


def test_unparseable_date():
    r = validate(good_invoice(invoice_date="13/45/2026"))
    assert "bad_date" in codes(r)


def test_tax_rate_not_allowed():
    r = validate(good_invoice(tax_rate=17.0, tax_amount=25.5, total=175.5))
    assert "tax_rate_not_allowed" in codes(r)


def test_missing_tax_id():
    r = validate(good_invoice(supplier_tax_id=None))
    assert "missing_tax_id" in codes(r)


def test_rounding_within_tolerance_is_fine():
    r = validate(good_invoice(tax_amount=30.004, total=180.01))
    assert r.status == "APPROVED"


def test_duplicate_in_batch_flags_second_occurrence():
    a = good_invoice()
    b = good_invoice()
    results = validate_batch([a, b])
    assert results[0].status == "APPROVED"
    assert "duplicate" in codes(results[1])


def test_duplicate_matching_ignores_case_and_spaces():
    a = good_invoice(invoice_number="inv-1001", supplier_name="ATLAS office supply")
    results = validate_batch([good_invoice(), a])
    assert "duplicate" in codes(results[1])


def test_custom_rules_allowed_rates():
    rules = Rules(allowed_tax_rates={0.0, 17.0})
    r = validate(good_invoice(tax_rate=17.0, tax_amount=25.5, total=175.5), rules)
    assert "tax_rate_not_allowed" not in codes(r)
