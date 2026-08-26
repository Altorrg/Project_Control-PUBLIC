from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator

from .kozos import ApiModel, LongText, ShortText


StatusCode = Literal["✓", "○", "!", "⮾", "H", "X", "II"]


class PartnerPayload(ApiModel):
    name: ShortText
    address: str = Field(default="", max_length=500)
    contact_person: ShortText = ""
    email: str = Field(default="", max_length=255)
    phone: str = Field(default="", max_length=80)
    org_type: str = Field(default="", max_length=120)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if value and ("@" not in value or "." not in value.rsplit("@", 1)[-1]):
            raise ValueError("Hibás e-mail-formátum.")
        return value


class PartnerChangeCreate(ApiModel):
    request_type: Literal["create", "update", "delete"]
    partner_id: int | None = None
    proposed: PartnerPayload
    reason: str = Field(default="", max_length=1000)


class ApprovalDecision(ApiModel):
    decision: Literal["approved", "rejected", "changes_requested"]
    comment: str = Field(default="", max_length=2000)
    proposed: PartnerPayload | None = None


class AssignmentCreate(ApiModel):
    project_id: int
    discipline_id: int
    task_id: int
    partner_id: int | None = None
    temporary_partner_request_id: int | None = None
    address: str = Field(default="", max_length=500)
    weight: Decimal = Field(default=Decimal("1"), ge=0, max_digits=10, decimal_places=2)
    main_note: LongText = ""
    status_code: StatusCode = "!"
    valid_until: date | None = None
    responsible: ShortText = ""
    due_date: date | None = None

    @field_validator("temporary_partner_request_id")
    @classmethod
    def require_one_partner(cls, value: int | None, info):
        if value is None and info.data.get("partner_id") is None:
            raise ValueError("Partner vagy ideiglenes partnerjavaslat kötelező.")
        return value


class AssignmentUpdate(ApiModel):
    discipline_id: int | None = None
    task_id: int | None = None
    partner_id: int | None = None
    temporary_partner_request_id: int | None = None
    address: str | None = Field(default=None, max_length=500)
    weight: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    main_note: str | None = Field(default=None, max_length=5000)
    status_code: StatusCode | None = None
    valid_until: date | None = None
    responsible: str | None = Field(default=None, max_length=255)
    due_date: date | None = None
    manual_override: bool | None = None


class EventRoundCreate(ApiModel):
    sent_date: date | None = None
    sent_note: str = Field(default="", max_length=5000)
    received_date: date | None = None
    received_note: str = Field(default="", max_length=5000)
    intervention_type_id: int | None = None
    status_code: StatusCode

    @field_validator("received_date")
    @classmethod
    def validate_order(cls, value: date | None, info):
        sent = info.data.get("sent_date")
        if value and sent and value < sent:
            raise ValueError("A beérkezés nem lehet korábbi a kiküldésnél.")
        return value


class EventRoundUpdate(EventRoundCreate):
    pass


class AttachmentInfo(ApiModel):
    id: int
    assignment_id: int
    storage_path: str
    original_name: str
    content_type: str
    size_bytes: int
    note: str = ""
    created_at: datetime | None = None
