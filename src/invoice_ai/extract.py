"""Local extraction via a vision-language model on Ollama. Nothing leaves the machine.

Routing:
- digital PDF (has a text layer)  -> text path: the model reads the exact text, no image (fast)
- scan / phone photo (no text)    -> vision path: the model reads the page image

In both paths the model only COPIES strings as printed. Normalization (numbers, dates, currency)
is done by deterministic code in normalize.py.
"""

from __future__ import annotations

import base64
import io
import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import pdfplumber
import pypdfium2 as pdfium
from PIL import Image

from .normalize import to_invoice
from .schema import Invoice

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "qwen2.5vl"
MAX_WIDTH = 1000

_S = {"type": "string"}
RAW_SCHEMA = {
    "type": "object",
    "properties": {
        "supplier_name": _S, "supplier_tax_id": _S, "invoice_number": _S,
        "invoice_date": _S, "due_date": _S, "currency": _S,
        "subtotal": _S, "tax_rate": _S, "tax_amount": _S, "total": _S,
        "line_items": {"type": "array", "items": {
            "type": "object",
            "properties": {"description": _S, "quantity": _S, "unit_price": _S, "amount": _S},
            "required": ["description", "quantity", "unit_price", "amount"],
        }},
    },
    "required": ["supplier_name", "supplier_tax_id", "invoice_number", "invoice_date", "due_date",
                 "currency", "subtotal", "tax_rate", "tax_amount", "total", "line_items"],
}

PROMPT = """Read this supplier invoice and copy the values below EXACTLY as they are printed (same digits, same separators, same symbols). Do not convert, correct or recompute anything. Use "" if a value is not printed.

- supplier_name: company that ISSUED the invoice (not the client / bill-to)
- supplier_tax_id: the supplier's VAT number / EIN / ICE, value only
- invoice_number: the invoice number (Invoice #, Invoice No, Facture n°, FACTURE N°)
- invoice_date: the invoice date as printed
- due_date: the due / payment date as printed (Due Date, Payment Due, Échéance, Date d'échéance)
- currency: the currency symbol or code used for amounts ($, €, £, DH, MAD...)
- subtotal: amount before tax (Subtotal, Total HT, Net, Montant HT)
- tax_rate: the tax label with its percentage (e.g. "TVA 5,5 %", "VAT @ 20%", "Sales Tax (8.25%)")
- tax_amount: the tax amount
- total: amount including tax (Total, TOTAL, Total TTC, Total Due, Montant TTC)
- line_items: every row of the items table: description, quantity, unit_price, amount"""


@dataclass
class Extraction:
    invoice: Invoice
    raw: dict
    seconds: float
    path: str  # "text" or "vision"


def load_page(path: Path) -> tuple[Image.Image, str]:
    """First page as an image, plus its text layer ('' for scans and photos)."""
    if path.suffix.lower() == ".pdf":
        page = pdfium.PdfDocument(str(path))[0]
        img = page.render(scale=MAX_WIDTH / page.get_width()).to_pil().convert("RGB")
        with pdfplumber.open(str(path)) as pdf:  # layout mode keeps table columns aligned per row
            text = pdf.pages[0].extract_text(layout=True) or ""
        lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
        return img, "\n".join(lines)
    img = Image.open(path).convert("RGB")
    if img.width > MAX_WIDTH:
        img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)), Image.LANCZOS)
    return img, ""


def _b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def extract(path: Path, model: str = DEFAULT_MODEL, timeout: float = 900) -> Extraction:
    img, text = load_page(path)
    if len(text) > 80:
        route = "text"
        msg = {"role": "user", "content": PROMPT + "\n\nInvoice text:\n" + text}
    else:
        route = "vision"
        msg = {"role": "user", "content": PROMPT, "images": [_b64(img)]}
    body = {"model": model, "messages": [msg], "format": RAW_SCHEMA, "stream": False,
            "options": {"temperature": 0, "num_ctx": 8192}}
    t0 = time.perf_counter()
    r = httpx.post(OLLAMA_URL, json=body, timeout=timeout)
    r.raise_for_status()
    raw = json.loads(r.json()["message"]["content"])
    return Extraction(to_invoice(raw), raw, time.perf_counter() - t0, route)
