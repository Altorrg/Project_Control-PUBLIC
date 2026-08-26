from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import Field

from .kozos import ApiModel, ShortText


class DailyProgressUpsert(ApiModel):
    project_id: int
    discipline_name: ShortText
    record_date: date
    phase: ShortText = ""
    days: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)
    actual_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=7, decimal_places=3)
    planned_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=7, decimal_places=3)


class ProjectDisciplineCreate(ApiModel):
    project_id: int
    name: ShortText
    code: str = Field(default="", max_length=40)
    visible: bool = True
    sort_order: int = 0

