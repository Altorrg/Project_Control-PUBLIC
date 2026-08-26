from __future__ import annotations

from datetime import date

from pydantic import Field, field_validator

from .kozos import ApiModel, LongText, ShortText


class OfferRequestData(ApiModel):
    """A kiadhato ajanlatkero valtozatban rogzitett, szerkesztheto tartalom."""

    work_number: ShortText = ""
    history: LongText = ""
    task_description: LongText = ""
    request_text: LongText = ""
    response_deadline: date | None = None
    schedule_text: LongText = ""
    finance_text: LongText = ""
    note: LongText = ""
    attachments: LongText = ""
    contacts: LongText = ""
    document_date: date | None = None

    @field_validator(
        "work_number",
        "history",
        "task_description",
        "request_text",
        "schedule_text",
        "finance_text",
        "note",
        "attachments",
        "contacts",
        mode="before",
    )
    @classmethod
    def normalize_empty_text(cls, value):
        return "" if value is None else value


class OfferRequestDocumentWrite(ApiModel):
    title: ShortText = Field(default="Árajánlatkérő")
    data: OfferRequestData

    @field_validator("title", mode="before")
    @classmethod
    def normalize_empty_title(cls, value):
        return "Árajánlatkérő" if value in (None, "") else value
