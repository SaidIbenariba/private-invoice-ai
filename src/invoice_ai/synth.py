"""Synthetic invoice generator with ground truth.

Four layouts with their own languages, number formats and date formats, a share of documents with
deliberate errors (wrong totals, duplicates, missing tax IDs...), and a share rendered as degraded
"phone photo" scans. Every document gets a truth JSON so extraction accuracy can be measured.
"""

from __future__ import annotations

import io
import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageFilter
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from .schema import Invoice, LineItem

W, H = A4
MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_EN_LONG = ["January", "February", "March", "April", "May", "June", "July", "August",
                  "September", "October", "November", "December"]

ANOMALIES = ["total_mismatch", "line_amount_mismatch", "tax_mismatch", "missing_tax_id",
             "due_before_issue", "duplicate"]


@dataclass
class Locale:
    key: str
    currency: str
    rates: list[float]
    suppliers: list[tuple[str, str]]  # (name, address)
    items: list[tuple[str, float, float]]  # (description, min price, max price)


LOCALES = {
    "us": Locale("us", "USD", [0.0, 8.25], [
        ("Brightline Logistics LLC", "2140 Commerce Pkwy, Dallas, TX 75201"),
        ("Northwind Office Supply Inc.", "88 Market St, San Francisco, CA 94105"),
        ("Keystone Packaging Co.", "410 Industrial Dr, Columbus, OH 43215"),
    ], [("Freight handling, pallet", 35, 90), ("Corrugated boxes 24x18x12", 1.2, 3.5),
        ("Stretch wrap roll 18in", 18, 32), ("Printer paper, case", 38, 55),
        ("Warehouse labor (hour)", 28, 45), ("Shipping labels, 1000 pack", 22, 40)]),
    "fr": Locale("fr", "EUR", [20.0, 10.0, 5.5], [
        ("Atelier Durand SARL", "12 rue des Lilas, 31000 Toulouse"),
        ("Transports Lefèvre SAS", "45 avenue Jean Jaurès, 69007 Lyon"),
        ("Bureau Plus Distribution", "8 boulevard Haussmann, 75009 Paris"),
    ], [("Transport palette Lyon-Paris", 85, 160), ("Ramette papier A4 80g", 4.5, 7.9),
        ("Cartouche toner noir", 49, 89), ("Prestation de maintenance", 60, 120),
        ("Carton double cannelure", 1.1, 2.9), ("Heure de manutention", 32, 48)]),
    "uk": Locale("uk", "GBP", [20.0], [
        ("Thames Valley Couriers Ltd", "Unit 4, Riverside Park, Reading RG1 8DB"),
        ("Pennine Print & Pack Ltd", "17 Mill Lane, Leeds LS1 4AB"),
    ], [("Same-day courier, zone 2", 22, 48), ("Printed flyers A5 (500)", 39, 75),
        ("Mailing bags, large (100)", 12, 21), ("Courier fuel surcharge", 4, 9),
        ("Design hours", 35, 60)]),
    "ma": Locale("ma", "MAD", [20.0, 10.0, 7.0], [
        ("Atlas Transport SARL", "Zone Industrielle Ain Sebaa, Casablanca"),
        ("Bureautique Rabat SARL", "23 Avenue Mohammed V, Rabat"),
    ], [("Transport marchandises Casa-Rabat", 650, 1400), ("Rame papier A4", 38, 55),
        ("Toner imprimante", 420, 780), ("Main d'oeuvre (heure)", 90, 160),
        ("Emballage carton", 9, 22)]),
}


# ---------- number / date formatting per locale ----------

def fmt_num(x: float, loc: str) -> str:
    if loc in ("us", "uk"):
        return f"{x:,.2f}"
    s = f"{x:,.2f}"  # 1,234.50 -> 1 234,50
    return s.replace(",", " ").replace(".", ",")


def fmt_money(x: float, loc: str) -> str:
    n = fmt_num(x, loc)
    return {"us": f"${n}", "uk": f"£{n}", "fr": f"{n} €", "ma": f"{n} DH"}[loc]


def fmt_date(d: date, loc: str) -> str:
    if loc == "us":
        return f"{MONTHS_EN[d.month - 1]} {d.day}, {d.year}"
    if loc == "uk":
        return f"{d.day} {MONTHS_EN_LONG[d.month - 1]} {d.year}"
    if loc == "fr":
        return d.strftime("%d/%m/%Y")
    return d.strftime("%d.%m.%Y")


def fmt_qty(q: float, loc: str) -> str:
    return str(int(q)) if q == int(q) else fmt_num(q, loc)


def tax_id(loc: str, rng: random.Random) -> str:
    digits = lambda n: "".join(str(rng.randint(0, 9)) for _ in range(n))
    return {"us": f"{digits(2)}-{digits(7)}", "fr": f"FR{digits(11)}",
            "uk": f"GB{digits(9)}", "ma": digits(15)}[loc]


# ---------- document generation ----------

def make_invoice(rng: random.Random, loc: Locale, anomaly: str | None, n: int) -> Invoice:
    supplier, _ = rng.choice(loc.suppliers)
    issued = date(2026, 9, 1) + timedelta(days=rng.randint(0, 35))
    due = issued + timedelta(days=rng.choice([15, 30, 45]))
    if anomaly == "due_before_issue":
        due = issued - timedelta(days=rng.randint(5, 20))

    items = []
    for desc, lo, hi in rng.sample(loc.items, rng.randint(2, min(5, len(loc.items)))):
        qty = float(rng.choice([1, 2, 3, 4, 5, 6, 8, 10, 12, 20, 25, 50]))
        price = round(rng.uniform(lo, hi), 2)
        items.append(LineItem(description=desc, quantity=qty, unit_price=price, amount=round(qty * price, 2)))
    if anomaly == "line_amount_mismatch":
        li = rng.choice(items)
        li.amount = round(li.amount + rng.choice([10, 25, 40, 100]), 2)

    subtotal = round(sum(li.amount for li in items), 2)
    rate = rng.choice(loc.rates)
    if anomaly == "tax_mismatch" and rate == 0.0:
        rate = max(loc.rates)
    tax = round(subtotal * rate / 100, 2)
    if anomaly == "tax_mismatch":
        tax = round(subtotal * (rate - 2) / 100, 2)
    total = round(subtotal + tax, 2)
    if anomaly == "total_mismatch":
        total = round(total + rng.choice([10, 20, 50, 90]), 2)

    prefix = {"us": "INV-", "fr": "F2026-", "uk": "TV", "ma": "2026/"}[loc.key]
    return Invoice(
        supplier_name=supplier,
        supplier_tax_id=None if anomaly == "missing_tax_id" else tax_id(loc.key, rng),
        invoice_number=f"{prefix}{1000 + n * 7 + rng.randint(0, 6)}",
        invoice_date=issued.isoformat(), due_date=due.isoformat(), currency=loc.currency,
        subtotal=subtotal, tax_rate=rate, tax_amount=tax, total=total, line_items=items,
    )


def _address(inv: Invoice, loc: Locale) -> str:
    return dict(loc.suppliers)[inv.supplier_name]


def _d(s: str) -> date:
    return date.fromisoformat(s)


def draw_us(c: Canvas, inv: Invoice, loc: Locale):
    k = "us"
    c.setFont("Helvetica-Bold", 17); c.drawString(50, H - 70, inv.supplier_name)
    c.setFont("Helvetica", 10); c.drawString(50, H - 88, _address(inv, loc))
    if inv.supplier_tax_id:
        c.drawString(50, H - 102, f"EIN: {inv.supplier_tax_id}")
    c.setFont("Helvetica-Bold", 30); c.setFillColor(HexColor("#9aa3ad")); c.drawRightString(W - 50, H - 75, "INVOICE")
    c.setFillColor(HexColor("#222222")); c.setFont("Helvetica", 10)
    for i, (a, b) in enumerate([("Invoice #", inv.invoice_number), ("Date", fmt_date(_d(inv.invoice_date), k)),
                                ("Due Date", fmt_date(_d(inv.due_date), k))]):
        c.drawRightString(W - 140, H - 105 - i * 15, a + ":"); c.drawRightString(W - 50, H - 105 - i * 15, b)
    c.setFont("Helvetica-Bold", 10); c.drawString(50, H - 160, "BILL TO")
    c.setFont("Helvetica", 10); c.drawString(50, H - 175, "Riverside Retail Group"); c.drawString(50, H - 189, "500 Main St, Austin, TX 78701")
    y = H - 230
    c.setFillColor(HexColor("#e9edf2")); c.rect(50, y - 6, W - 100, 22, fill=1, stroke=0); c.setFillColor(HexColor("#222222"))
    c.setFont("Helvetica-Bold", 10)
    c.drawString(58, y, "Description"); c.drawRightString(360, y, "Qty"); c.drawRightString(450, y, "Unit Price"); c.drawRightString(W - 58, y, "Amount")
    c.setFont("Helvetica", 10)
    for li in inv.line_items:
        y -= 24
        c.drawString(58, y, li.description); c.drawRightString(360, y, fmt_qty(li.quantity, k))
        c.drawRightString(450, y, fmt_money(li.unit_price, k)); c.drawRightString(W - 58, y, fmt_money(li.amount, k))
        c.setStrokeColor(HexColor("#dddddd")); c.line(50, y - 8, W - 50, y - 8)
    y -= 40
    rows = [("Subtotal", inv.subtotal), (f"Sales Tax ({fmt_num(inv.tax_rate, k).rstrip('0').rstrip('.')}%)", inv.tax_amount)]
    for a, b in rows:
        c.drawRightString(450, y, a); c.drawRightString(W - 58, y, fmt_money(b, k)); y -= 18
    c.setFont("Helvetica-Bold", 12); c.drawRightString(450, y - 4, "TOTAL"); c.drawRightString(W - 58, y - 4, fmt_money(inv.total, k))
    c.setFont("Helvetica-Oblique", 9); c.drawString(50, 60, "Thank you for your business. Payment by ACH or check.")


def draw_fr(c: Canvas, inv: Invoice, loc: Locale):
    k = "fr"
    blue = HexColor("#1f4e9c")
    c.setFillColor(blue); c.setFont("Helvetica-Bold", 30); c.drawString(50, H - 80, "FACTURE")
    c.setFillColor(HexColor("#222222")); c.setFont("Helvetica-Bold", 12); c.drawRightString(W - 50, H - 60, inv.supplier_name)
    c.setFont("Helvetica", 9); c.drawRightString(W - 50, H - 74, _address(inv, loc))
    if inv.supplier_tax_id:
        c.drawRightString(W - 50, H - 87, f"N° TVA intracom. : {inv.supplier_tax_id}")
    c.setStrokeColor(blue); c.rect(50, H - 175, 250, 65, stroke=1, fill=0)
    c.setFont("Helvetica", 10)
    c.drawString(60, H - 128, f"Facture n° : {inv.invoice_number}")
    c.drawString(60, H - 145, f"Date : {fmt_date(_d(inv.invoice_date), k)}")
    c.drawString(60, H - 162, f"Échéance : {fmt_date(_d(inv.due_date), k)}")
    c.drawString(330, H - 128, "Client :"); c.drawString(330, H - 145, "Boulangerie Martin")
    c.drawString(330, H - 162, "3 place du Capitole, 31000 Toulouse")
    y = H - 220
    c.setFillColor(blue); c.rect(50, y - 6, W - 100, 22, fill=1, stroke=0); c.setFillColor(white)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(58, y, "Désignation"); c.drawRightString(350, y, "Qté"); c.drawRightString(440, y, "PU HT"); c.drawRightString(W - 58, y, "Total HT")
    c.setFillColor(HexColor("#222222")); c.setFont("Helvetica", 10)
    for li in inv.line_items:
        y -= 24
        c.drawString(58, y, li.description); c.drawRightString(350, y, fmt_qty(li.quantity, k))
        c.drawRightString(440, y, fmt_money(li.unit_price, k)); c.drawRightString(W - 58, y, fmt_money(li.amount, k))
    y -= 40
    rate = fmt_num(inv.tax_rate, k).replace(",00", "").replace(",50", ",5")
    for a, b in [("Total HT", inv.subtotal), (f"TVA {rate} %", inv.tax_amount)]:
        c.drawRightString(440, y, a); c.drawRightString(W - 58, y, fmt_money(b, k)); y -= 18
    c.setFillColor(HexColor("#eef2fa")); c.rect(330, y - 10, W - 380, 24, fill=1, stroke=0); c.setFillColor(HexColor("#222222"))
    c.setFont("Helvetica-Bold", 12); c.drawRightString(440, y - 2, "Total TTC"); c.drawRightString(W - 58, y - 2, fmt_money(inv.total, k))
    c.setFont("Helvetica", 8)
    c.drawString(50, 70, "Conditions de paiement : virement à réception. Pénalités de retard : 3 fois le taux d'intérêt légal.")
    c.drawString(50, 58, "Indemnité forfaitaire pour frais de recouvrement : 40 €.")


def draw_uk(c: Canvas, inv: Invoice, loc: Locale):
    k = "uk"
    teal = HexColor("#0f766e")
    c.setFillColor(teal); c.rect(0, H - 110, W, 110, fill=1, stroke=0)
    c.setFillColor(white); c.setFont("Helvetica-Bold", 20); c.drawString(50, H - 55, inv.supplier_name)
    c.setFont("Helvetica", 10); c.drawString(50, H - 74, _address(inv, loc))
    if inv.supplier_tax_id:
        c.drawString(50, H - 90, f"VAT Reg No: {inv.supplier_tax_id}")
    c.setFont("Helvetica-Bold", 16); c.drawRightString(W - 50, H - 55, "TAX INVOICE")
    c.setFillColor(HexColor("#222222")); c.setFont("Helvetica", 10)
    c.drawString(50, H - 145, f"Invoice No: {inv.invoice_number}")
    c.drawString(50, H - 160, f"Invoice Date: {fmt_date(_d(inv.invoice_date), k)}")
    c.drawString(50, H - 175, f"Payment Due: {fmt_date(_d(inv.due_date), k)}")
    c.drawRightString(W - 50, H - 145, "Invoice to: Harbour Books Ltd"); c.drawRightString(W - 50, H - 160, "2 Quay Street, Bristol BS1 4DJ")
    y = H - 220
    c.setFont("Helvetica-Bold", 9); c.setFillColor(teal)
    c.drawString(50, y, "ITEM"); c.drawRightString(360, y, "QTY"); c.drawRightString(450, y, "PRICE"); c.drawRightString(W - 50, y, "LINE TOTAL")
    c.setFillColor(HexColor("#222222")); c.setFont("Helvetica", 10)
    for li in inv.line_items:
        y -= 26
        c.drawString(50, y, li.description); c.drawRightString(360, y, fmt_qty(li.quantity, k))
        c.drawRightString(450, y, fmt_money(li.unit_price, k)); c.drawRightString(W - 50, y, fmt_money(li.amount, k))
    y -= 45
    c.setStrokeColor(teal); c.line(330, y + 20, W - 50, y + 20)
    for a, b in [("Net", inv.subtotal), (f"VAT @ {int(inv.tax_rate)}%", inv.tax_amount)]:
        c.drawRightString(450, y, a); c.drawRightString(W - 50, y, fmt_money(b, k)); y -= 18
    c.setFont("Helvetica-Bold", 13); c.drawRightString(450, y - 4, "Total Due"); c.drawRightString(W - 50, y - 4, fmt_money(inv.total, k))
    c.setFont("Helvetica", 8); c.drawString(50, 60, "Bank: Lloyds  Sort code 30-90-12  Account 12345678. Please quote the invoice number.")


def draw_ma(c: Canvas, inv: Invoice, loc: Locale):
    k = "ma"
    c.setFont("Helvetica-Bold", 16); c.drawCentredString(W / 2, H - 60, inv.supplier_name.upper())
    c.setFont("Helvetica", 9); c.drawCentredString(W / 2, H - 75, _address(inv, loc))
    if inv.supplier_tax_id:
        c.drawCentredString(W / 2, H - 88, f"ICE : {inv.supplier_tax_id}   -   RC : 48213   -   IF : 1528841")
    c.setLineWidth(1.2); c.line(50, H - 100, W - 50, H - 100)
    c.setFont("Helvetica-Bold", 13); c.drawString(50, H - 130, f"FACTURE N° {inv.invoice_number}")
    c.setFont("Helvetica", 10)
    c.drawString(50, H - 148, f"Date : {fmt_date(_d(inv.invoice_date), k)}")
    c.drawString(50, H - 163, f"Date d'échéance : {fmt_date(_d(inv.due_date), k)}")
    c.drawString(340, H - 130, "Client : Société Al Amal SARL"); c.drawString(340, H - 148, "Hay Riad, Rabat")
    cols = [50, 300, 360, 455, W - 50]
    y = H - 200
    c.setLineWidth(0.8)
    c.rect(cols[0], y - 8, cols[-1] - cols[0], 24)
    c.setFont("Helvetica-Bold", 10)
    for x, t in zip(cols[:-1], ["Désignation", "Qté", "P.U. HT", "Montant HT"]):
        c.drawString(x + 6, y, t)
    c.setFont("Helvetica", 10)
    top = y - 8
    for li in inv.line_items:
        y -= 24
        c.drawString(cols[0] + 6, y, li.description); c.drawRightString(cols[2] - 6, y, fmt_qty(li.quantity, k))
        c.drawRightString(cols[3] - 6, y, fmt_num(li.unit_price, k)); c.drawRightString(cols[4] - 6, y, fmt_num(li.amount, k))
    bottom = y - 10
    c.rect(cols[0], bottom, cols[-1] - cols[0], top - bottom)
    for x in cols[1:-1]:
        c.line(x, top + 24, x, bottom)
    y = bottom - 25
    rate = fmt_num(inv.tax_rate, k).replace(",00", "")
    for a, b in [("Montant HT", inv.subtotal), (f"TVA {rate}%", inv.tax_amount), ("Montant TTC", inv.total)]:
        c.rect(cols[2], y - 8, cols[-1] - cols[2], 22)
        c.setFont("Helvetica-Bold" if a == "Montant TTC" else "Helvetica", 10)
        c.drawString(cols[2] + 6, y, a); c.drawRightString(cols[4] - 6, y, fmt_money(b, k)); y -= 22
    c.setFont("Helvetica", 9)
    c.drawString(50, 80, "Arrêtée la présente facture à la somme indiquée ci-dessus. Paiement par virement bancaire.")


DRAW = {"us": draw_us, "fr": draw_fr, "uk": draw_uk, "ma": draw_ma}


def render_pdf(inv: Invoice, loc: Locale) -> bytes:
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=A4)
    DRAW[loc.key](c, inv, loc)
    c.showPage(); c.save()
    return buf.getvalue()


def degrade_to_photo(pdf_bytes: bytes, rng: random.Random) -> Image.Image:
    """Simulate a phone photo: lower resolution, slight rotation, uneven light, blur, noise, JPEG."""
    page = pdfium.PdfDocument(pdf_bytes)[0]
    img = page.render(scale=110 / 72).to_pil().convert("RGB")
    img = img.rotate(rng.uniform(-2.5, 2.5), expand=True, fillcolor=(214, 208, 196), resample=Image.BICUBIC)
    arr = np.asarray(img).astype(np.float32)
    h, w, _ = arr.shape
    shade = np.linspace(1.0, rng.uniform(0.78, 0.9), w)[None, :, None] * np.linspace(rng.uniform(0.9, 1.0), 1.0, h)[:, None, None]
    arr = arr * shade + np.random.default_rng(rng.randint(0, 10**6)).normal(0, 6, arr.shape)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(rng.uniform(0.5, 0.9)))
    return img


def generate(out_dir: Path, n: int = 24, seed: int = 7, anomaly_share: float = 0.35, photo_share: float = 0.3) -> None:
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    truth_dir = out_dir / "truth"
    truth_dir.mkdir(exist_ok=True)
    locs = list(LOCALES.values())
    made: list[Invoice] = []
    n_anom = round(n * anomaly_share)
    plan = [ANOMALIES[i % len(ANOMALIES)] for i in range(n_anom)] + [None] * (n - n_anom)
    rng.shuffle(plan)
    if plan[0] == "duplicate":  # a duplicate needs an earlier invoice to copy
        j = next(i for i, a in enumerate(plan) if a != "duplicate")
        plan[0], plan[j] = plan[j], plan[0]

    for i, anomaly in enumerate(plan, 1):
        loc = locs[(i - 1) % len(locs)]
        inv = make_invoice(rng, loc, anomaly, i)
        if anomaly == "duplicate":
            same = [m for m in made if m.currency == loc.currency] or made
            src = rng.choice(same)
            inv.supplier_name, inv.invoice_number, inv.supplier_tax_id = src.supplier_name, src.invoice_number, src.supplier_tax_id
            loc = next(l for l in locs if l.currency == src.currency)
            inv.currency = src.currency
        made.append(inv)

        doc_id = f"inv_{i:03d}"
        pdf = render_pdf(inv, loc)
        is_photo = rng.random() < photo_share
        if is_photo:
            fname = f"{doc_id}.jpg"
            degrade_to_photo(pdf, rng).save(out_dir / fname, quality=62)
        else:
            fname = f"{doc_id}.pdf"
            (out_dir / fname).write_bytes(pdf)
        truth = {"doc_id": doc_id, "file": fname, "layout": loc.key, "photo": is_photo,
                 "anomaly": anomaly, "invoice": inv.model_dump()}
        (truth_dir / f"{doc_id}.json").write_text(json.dumps(truth, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    import sys
    generate(Path(sys.argv[1] if len(sys.argv) > 1 else "data/samples"))
