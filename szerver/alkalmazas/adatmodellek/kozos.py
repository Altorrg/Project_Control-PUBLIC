from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


T = TypeVar("T")
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Page(ApiModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class AuditFields(ApiModel):
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DateRange(ApiModel):
    start: date | None = None
    end: date | None = None

    @field_validator("end")
    @classmethod
    def validate_end(cls, value: date | None, info):
        start = info.data.get("start")
        if value and start and value < start:
            raise ValueError("A záródátum nem lehet korábbi a kezdődátumnál.")
        return value


class Money(ApiModel):
    amount: Decimal = Field(decimal_places=2, max_digits=18)
    currency: str = Field(default="HUF", min_length=3, max_length=3)
