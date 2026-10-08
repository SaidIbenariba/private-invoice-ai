"""Canonical invoice schema shared by extraction, validation, evaluation and export."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str = ""
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None


class Invoice(BaseModel):
    supplier_name: str | None = None
    supplier_tax_id: str | None = Field(None, description="VAT number, ICE or other tax ID of the supplier")
    invoice_number: str | None = None
    invoice_date: str | None = Field(None, description="ISO date YYYY-MM-DD")
    due_date: str | None = Field(None, description="ISO date YYYY-MM-DD")
    currency: str | None = Field(None, description="ISO 4217 code, e.g. EUR, USD, GBP, MAD")
    subtotal: float | None = Field(None, description="Total before tax")
    tax_rate: float | None = Field(None, description="Tax rate in percent, e.g. 20 for 20%")
    tax_amount: float | None = None
    total: float | None = Field(None, description="Total including tax")
    line_items: list[LineItem] = Field(default_factory=list)


HEADER_FIELDS = [
    "supplier_name",
    "supplier_tax_id",
    "invoice_number",
    "invoice_date",
    "due_date",
    "currency",
    "subtotal",
    "tax_rate",
    "tax_amount",
    "total",
]

NUMERIC_FIELDS = {"subtotal", "tax_rate", "tax_amount", "total"}
