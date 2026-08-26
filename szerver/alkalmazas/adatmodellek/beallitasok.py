from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator

from .kozos import ApiModel, LongText, ShortText


class DailyRateUpsert(ApiModel):
    year: int = Field(ge=1900, le=2200)
    daily_rate: Decimal = Field(ge=0, max_digits=18, decimal_places=2)


class ProjectPhaseCreate(ApiModel):
    phase_name: ShortText
    sort_order: int = Field(default=0, ge=-10000, le=10000)


class DisciplineVisibilityUpdate(ApiModel):
    visible: bool


class CalendarExceptionCreate(ApiModel):
    exception_date: date
    exception_type: Literal["Munkanap", "Munkaszüneti nap", "Pihenőnap"]
    name: ShortText = ""


class OfferRequestSettingsUpsert(ApiModel):
    history: LongText = ""
    task_description: LongText = ""


class ProjectDataSheetMetadata(ApiModel):
    directorate: ShortText = ""
    project_role: ShortText = ""
    business_agreement: LongText = ""
    project_scale: ShortText = ""
    project_source: ShortText = ""
    nationally_significant: bool = False


class ProjectCompanyContactWrite(ApiModel):
    name: ShortText
    job_title: ShortText = ""
    email: ShortText = ""
    phone: ShortText = ""
    display_order: int = Field(default=0, ge=-10000, le=10000)


class ScheduleKeyWrite(ApiModel):
    code: ShortText
    description: LongText = ""
    start_event: ShortText = ""
    end_event: ShortText = ""
    note: LongText = ""
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("A jelkulcs kötelező.")
        return normalized
