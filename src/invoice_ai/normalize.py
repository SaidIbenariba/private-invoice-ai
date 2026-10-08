"""Deterministic normalization of raw strings read off the document.

The model copies text; this code turns it into numbers, ISO dates and currency codes. Keeping this
out of the model makes results reproducible and testable.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from .schema import Invoice, LineItem

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_number(raw: str | None) -> float | None:
    if not raw:
        return None
    s = re.sub(r"[^\d,.\-]", "", raw.replace(" ", " ").replace("\xa0", " ").replace(" ", ""))
    if not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        # whichever separator comes last is the decimal one
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_date(raw: str | None) -> str | None:
    """ISO string when parseable; the raw string otherwise (so validation can flag it); None if empty."""
    if not raw or not raw.strip():
        return None
    s = raw.strip()
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    candidates = []
    if m:
        candidates.append((int(m[1]), int(m[2]), int(m[3])))
    m = re.search(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", s)
    if m:  # day first: FR / MA / UK numeric formats
        candidates.append((int(m[3]), int(m[2]), int(m[1])))
    m = re.search(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", s)
    if m and m[1].lower() in _MONTHS:
        candidates.append((int(m[3]), _MONTHS[m[1].lower()], int(m[2])))
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{4})", s)
    if m and m[2].lower() in _MONTHS:
        candidates.append((int(m[3]), _MONTHS[m[2].lower()], int(m[1])))
    for y, mo, d in candidates:
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            continue
    return s


def parse_rate(raw: str | None) -> float | None:
    if not raw:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", raw) or re.search(r"(\d+(?:[.,]\d+)?)", raw)
    return float(m[1].replace(",", ".")) if m else None


_SYMBOLS = [("€", "EUR"), ("£", "GBP"), ("$", "USD"), ("DH", "MAD"), ("MAD", "MAD"),
            ("EUR", "EUR"), ("GBP", "GBP"), ("USD", "USD"), ("DIRHAM", "MAD")]


def detect_currency(*texts: str | None) -> str | None:
    blob = " ".join(t for t in texts if t).upper()
    for sym, code in _SYMBOLS:
        if sym in blob:
            return code
    return None


def clean_tax_id(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None
    s = raw.split(":")[-1] if ":" in raw else raw
    m = re.search(r"[A-Z]{0,2}[\d][\d\- ]{5,}[\d]", s.upper())
    return m[0].replace(" ", "") if m else s.strip() or None


_INV_LABEL = re.compile(
    r"^\s*(?:tax\s+)?(?:invoice|facture|factura|rechnung|bill)?\s*(?:number|no\.?|n°|nº|num(?:éro|ero)?|#)?\s*[:#.]?\s*",
    re.IGNORECASE,
)


def clean_invoice_number(raw: str | None) -> str | None:
    """Drop a label the model may copy along with the value ("FACTURE N° 2026/1168" -> "2026/1168")."""
    if not raw or not raw.strip():
        return None
    s = _INV_LABEL.sub("", raw.strip(), count=1).strip()
    return s or raw.strip()


def to_invoice(raw: dict) -> Invoice:
    """Build a clean Invoice from the model's raw-string output."""
    g = lambda k: (raw.get(k) or "").strip()
    items = []
    for li in raw.get("line_items") or []:
        items.append(LineItem(
            description=(li.get("description") or "").strip(),
            quantity=parse_number(li.get("quantity")),
            unit_price=parse_number(li.get("unit_price")),
            amount=parse_number(li.get("amount")),
        ))
    amounts_text = [g("total"), g("subtotal"), g("tax_amount"), g("currency")]
    return Invoice(
        supplier_name=g("supplier_name") or None,
        supplier_tax_id=clean_tax_id(g("supplier_tax_id")),
        invoice_number=clean_invoice_number(g("invoice_number")),
        invoice_date=parse_date(g("invoice_date")),
        due_date=parse_date(g("due_date")),
        currency=detect_currency(g("currency")) or detect_currency(*amounts_text),
        subtotal=parse_number(g("subtotal")),
        tax_rate=parse_rate(g("tax_rate")),
        tax_amount=parse_number(g("tax_amount")),
        total=parse_number(g("total")),
        line_items=items,
    )
