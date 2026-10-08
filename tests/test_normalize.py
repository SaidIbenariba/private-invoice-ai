import pytest

from invoice_ai.normalize import (
    clean_invoice_number, clean_tax_id, detect_currency, parse_date, parse_number, parse_rate,
)


@pytest.mark.parametrize("raw,expected", [
    ("1 234,50 €", 1234.50),
    ("$1,234.50", 1234.50),
    ("£708.91", 708.91),
    ("12 696,14 DH", 12696.14),
    ("13 965,75", 13965.75),
    ("6,72 €", 6.72),
    ("329,45", 329.45),
    ("4,270.61", 4270.61),
    ("1.234,50", 1234.50),
    ("25", 25.0),
    ("1 921,20 €", 1921.20),
    ("", None),
    ("n/a", None),
])
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Sep 14, 2026", "2026-09-14"),
    ("14 September 2026", "2026-09-14"),
    ("15/09/2026", "2026-09-15"),
    ("04.10.2026", "2026-10-04"),
    ("2026-10-04", "2026-10-04"),
    ("Date : 04.10.2026", "2026-10-04"),
    ("", None),
])
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


def test_unparseable_date_is_kept_raw_so_validation_flags_it():
    assert parse_date("31/02/2026") == "31/02/2026"


@pytest.mark.parametrize("raw,expected", [
    ("TVA 5,5 %", 5.5), ("VAT @ 20%", 20.0), ("Sales Tax (8.25%)", 8.25), ("20", 20.0), ("", None),
])
def test_parse_rate(raw, expected):
    assert parse_rate(raw) == expected


@pytest.mark.parametrize("texts,expected", [
    (["1 234,50 €"], "EUR"), (["$12.00"], "USD"), (["£3"], "GBP"), (["13 965,75 DH"], "MAD"),
    (["MAD"], "MAD"), (["EUR"], "EUR"), (["12.00"], None),
])
def test_detect_currency(texts, expected):
    assert detect_currency(*texts) == expected


@pytest.mark.parametrize("raw,expected", [
    ("FACTURE N° 2026/1168", "2026/1168"),
    ("Facture n° : F2026-1071", "F2026-1071"),
    ("Invoice #: INV-1012", "INV-1012"),
    ("Invoice No: TV1023", "TV1023"),
    ("INV-1012", "INV-1012"),
    ("2026/1168", "2026/1168"),
    ("", None),
])
def test_clean_invoice_number(raw, expected):
    assert clean_invoice_number(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("N° TVA intracom. : FR48477718341", "FR48477718341"),
    ("VAT Reg No: GB123456789", "GB123456789"),
    ("ICE : 169784649366578", "169784649366578"),
    ("EIN: 12-3456789", "12-3456789"),
    ("", None),
])
def test_clean_tax_id(raw, expected):
    assert clean_tax_id(raw) == expected
