from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator

from .kozos import ApiModel, LongText, ShortText


IdempotencyKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


class ProjectCreate(ApiModel):
    name: ShortText
    idempotency_key: IdempotencyKey | None = None
    work_number: ShortText = ""
    responsible_company: ShortText = ""
    contract_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    contract_subject: LongText | None = None
    customer: ShortText = ""
    main_customer: ShortText = ""
    status: ShortText = "Aktív"

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value:
            raise ValueError("A projekt neve kötelező.")
        return value

    @field_validator("responsible_company")
    @classmethod
    def normalize_responsible_company(cls, value: str) -> str:
        return value.strip()


class ProjectUpdate(ApiModel):
    name: ShortText | None = None
    work_number: ShortText | None = None
    responsible_company: ShortText | None = None
    contract_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    contract_subject: LongText | None = None
    customer: ShortText | None = None
    main_customer: ShortText | None = None
    status: ShortText | None = None

    @field_validator("responsible_company")
    @classmethod
    def normalize_responsible_company(cls, value: str | None) -> str | None:
        return value.strip() if value else value


class Project(ApiModel):
    id: int
    name: str
    work_number: str = ""
    responsible_company: str = ""
    contract_value: Decimal | None = None
    contract_subject: str | None = None
    customer: str = ""
    main_customer: str = ""
    status: str = ""
    created_at: datetime | None = None
