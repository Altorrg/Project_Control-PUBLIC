from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from .kozos import ApiModel, ShortText


AIMessageText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
ModuleName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class AIAssistantHistoryMessage(ApiModel):
    role: Literal["user", "assistant"]
    content: AIMessageText


class AIAssistantRequest(ApiModel):
    message: AIMessageText
    project_id: int | None = Field(default=None, gt=0)
    module: ModuleName | None = None
    history: list[AIAssistantHistoryMessage] = Field(default_factory=list, max_length=20)


class AIAssistantSource(ApiModel):
    label: ShortText
    reference: ShortText | None = None


class AIAssistantResponse(ApiModel):
    answer: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]
    sources: list[AIAssistantSource] = Field(default_factory=list, max_length=20)
    request_id: ShortText
    suggestions: list[ShortText] = Field(default_factory=list, max_length=10)
