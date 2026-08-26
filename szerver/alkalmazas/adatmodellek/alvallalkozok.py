from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field
from pydantic import model_validator

from .kozos import ApiModel


OfferStatus = Literal["Kiküldésre vár", "Kiküldve", "Elutasítva"]


class WorkflowCreate(ApiModel):
    project_id: int
    display_order: int = Field(default=10, ge=0)
    company_name: str = Field(min_length=1, max_length=255)
    discipline: str = Field(default="", max_length=255)
    code: str = Field(default="", max_length=80)
    finance_class: str = Field(default="", max_length=120)
    status_note: str = Field(default="", max_length=2000)
    preliminary_estimate: str = Field(default="", max_length=120)
    offer_status: OfferStatus = "Kiküldésre vár"
    offer_date: str = Field(default="", max_length=40)
    offer_link: str = Field(default="", max_length=1000)
    received_date: str = Field(default="", max_length=40)
    received_link: str = Field(default="", max_length=1000)
    offer_price: str = Field(default="", max_length=120)
    acceptance: str = Field(default="", max_length=120)
    feedback: str = Field(default="", max_length=2000)
    contract_total: str = Field(default="", max_length=120)
    contract_fee: str = Field(default="", max_length=120)
    copyright_fee: str = Field(default="", max_length=120)
    guarantee: str = Field(default="", max_length=120)
    notification: str = Field(default="", max_length=120)
    draft: str = Field(default="", max_length=120)
    signature_status: str = Field(default="", max_length=120)
    signature_date: str = Field(default="", max_length=40)
    closing_note: str = Field(default="", max_length=2000)
    currency: str = Field(default="HUF", min_length=3, max_length=3)
    vat_type: str = Field(default="Netto", max_length=40)
    no_offer: bool = False
    current_step: int = Field(default=1, ge=1, le=20)
    part_count: int = Field(default=1, ge=1, le=100)
    modified_fee: str = Field(default="", max_length=120)
    modified_copyright_fee: str = Field(default="", max_length=120)
    modified_total: str = Field(default="", max_length=120)
    modification_date: str = Field(default="", max_length=40)
    modification_note: str = Field(default="", max_length=2000)
    reopen_completed_payments: bool = False


class WorkflowUpdate(WorkflowCreate):
    project_id: int


class ContractMatrixCell(ApiModel):
    project_id: int
    stage_id: int | None = None
    reference_id: str = Field(max_length=120)
    column_code: str = Field(default="", max_length=80)
    percent: float | None = None
    amount: float = 0
    text_value: str = Field(default="", max_length=1000)
    calculation_source: Literal["percent", "amount", "text"] = "amount"
    reopen_completed_payment: bool = False


class WorkflowScheduleKeyAssignment(ApiModel):
    financial_phase_no: int = Field(ge=0, le=5)
    schedule_key_id: int = Field(gt=0)


class WorkflowScheduleKeyAssignments(ApiModel):
    assignments: list[WorkflowScheduleKeyAssignment] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_unique_assignments(self):
        pairs = [
            (item.financial_phase_no, item.schedule_key_id)
            for item in self.assignments
        ]
        if len(pairs) != len(set(pairs)):
            raise ValueError("Egy jelkulcs egy penzugyi fazisban csak egyszer szerepelhet.")
        return self


class OfferPart(ApiModel):
    phase_name: str = Field(min_length=1, max_length=255)
    amount: str = Field(default="", max_length=120)
    optional: bool = False


class ContractPart(ApiModel):
    phase_name: str = Field(min_length=1, max_length=255)
    fee: str = Field(default="", max_length=120)
    copyright_fee: str = Field(default="", max_length=120)
    total: str = Field(default="", max_length=120)


class ContractChangeCreate(ApiModel):
    change_date: date | None = None
    modified_fee: str = Field(default="", max_length=120)
    modified_copyright_fee: str = Field(default="", max_length=120)
    modified_total: str = Field(default="", max_length=120)
    reason: str = Field(default="", max_length=2000)
    reopen_completed_payments: bool = False


class ContractStageCreate(ApiModel):
    name: str = Field(min_length=1, max_length=255)
    stage_date: date
    sort_order: int = Field(default=0, ge=0)


class ContractBaseValue(ApiModel):
    reference_id: str = Field(min_length=1, max_length=120)
    amount: float = Field(default=0, ge=0)
    reopen_completed_payments: bool = False


class WorkflowStepRequest(ApiModel):
    step: int = Field(ge=1, le=6)
    action: Literal["close", "reopen"]
    allow_offer_mismatch: bool = False


class FolderCreate(ApiModel):
    name: str = Field(min_length=1, max_length=255)
    code: str = Field(default="", max_length=80)
    display_order: int = Field(default=0, ge=0)


class FolderReorderRequest(ApiModel):
    folder_ids: list[int] = Field(min_length=1)


class SubcontractorCreate(ApiModel):
    name: str = Field(min_length=1, max_length=255)
    category: str = Field(default="", max_length=255)
    code: str = Field(default="", max_length=80)


class WorkflowRecord(WorkflowCreate):
    id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    legacy_payload: dict[str, Any] = {}
