from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from .kozos import ApiModel


PaymentStatus = Literal["Várható", "TIG kiállítva", "Számlázva", "Pénzügyileg teljesítve"]


class PaymentCreate(ApiModel):
    project_id: int
    workflow_id: int | None = None
    payment_date: date | None = None
    amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    verification_link: str = Field(default="", max_length=1000)
    is_revenue: bool = False
    reference: str = Field(default="", max_length=255)
    invoice_number: str = Field(default="", max_length=120)
    status: PaymentStatus = "Várható"
    tig_date: date | None = None
    invoice_date: date | None = None

    @model_validator(mode="after")
    def validate_financial_step(self) -> "PaymentCreate":
        if self.status in {"TIG kiállítva", "Számlázva", "Pénzügyileg teljesítve"} and self.tig_date is None:
            raise ValueError("A kiválasztott pénzügyi státuszhoz kötelező a TIG dátuma.")
        if self.status in {"Számlázva", "Pénzügyileg teljesítve"}:
            if self.invoice_date is None or not self.invoice_number.strip():
                raise ValueError("A számlázott státuszhoz kötelező a számla dátuma és száma.")
        if self.status == "Pénzügyileg teljesítve":
            if self.payment_date is None or self.amount <= 0:
                raise ValueError("A pénzügyi teljesítéshez kötelező a teljesítés dátuma és pozitív összege.")
        return self


class FinanceMapping(ApiModel):
    project_id: int
    workflow_id: int
    discipline_name: str = Field(min_length=1, max_length=255)
