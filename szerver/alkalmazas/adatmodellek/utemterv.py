from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from .kozos import ApiModel, LongText, ShortText


CalculationType = Literal["Naptári nap", "Munkanap", "Hónap"]
MilestoneDateType = Literal["Fix dátum", "Ütemterv sorhoz kötve", "Másik mérföldkőhöz kötve"]


class ScheduleSettingsWrite(ApiModel):
    project_start: date


class ScheduleRowCreate(ApiModel):
    project_id: int
    position: int = Field(gt=0)
    section: ShortText | None = None
    phase_code: ShortText | None = None
    schedule_key_id: int | None = Field(default=None, gt=0)
    financial_phase_no: int | None = Field(default=None, ge=0, le=5)
    phase_name: ShortText
    reference_name: ShortText = "Projekt kezdete"
    days: int = Field(default=1, ge=1, le=36500)
    delay: int = Field(default=0, ge=-36500, le=36500)
    manual_start: date | None = None
    calc_type: CalculationType = "Naptári nap"


class ScheduleCalculationRequest(ApiModel):
    project_start: date


class ScheduleReorderRequest(ApiModel):
    row_ids: list[int] = Field(min_length=1, max_length=1000)


class CalculatedScheduleRow(ApiModel):
    id: int | None = None
    position: int
    section: str | None = None
    phase_code: str | None = None
    schedule_key_id: int | None = None
    financial_phase_no: int | None = None
    phase_name: str
    reference_name: str
    days: int
    delay: int
    manual_start: date | None = None
    calc_type: CalculationType
    start_date: date
    end_date: date


class ContractSectionWrite(ApiModel):
    project_id: int
    section_no: int = Field(ge=0, le=5)
    original_fee: float = Field(default=0, ge=0)
    modified_fee: float = Field(default=0, ge=0)
    fee_percent: float = Field(default=0, ge=0, le=100)
    copyright_percent: float = Field(default=0, ge=0, le=100)
    section_date: date | None = None
    note: LongText = ""


class ProjectMilestoneWrite(ApiModel):
    project_id: int
    sequence_no: int = Field(default=0, ge=0)
    name: ShortText = ""
    short_name: ShortText = ""
    official_name: ShortText = ""
    elapsed_months: int = Field(default=0, ge=0, le=1200)
    fee_percent: float = Field(default=0, ge=0, le=100)
    copyright_percent: float = Field(default=0, ge=0, le=100)
    description: LongText = ""
    planned_date: date | None = None
    phase_no: int = Field(default=1, ge=0, le=5)
    actual_date: date | None = None
    date_type: MilestoneDateType = "Fix dátum"
    schedule_row_id: int | None = Field(default=None, gt=0)
    reference_name: ShortText = ""
    offset_days: int = Field(default=0, ge=-36500, le=36500)

    @model_validator(mode="after")
    def normalize_names(self) -> ProjectMilestoneWrite:
        official_name = self.official_name or self.name or self.short_name
        short_name = self.short_name or self.name or official_name
        if not official_name:
            raise ValueError("A mérföldkő hivatalos vagy rövid neve kötelező.")
        self.official_name = official_name
        self.short_name = short_name
        self.name = official_name
        return self
