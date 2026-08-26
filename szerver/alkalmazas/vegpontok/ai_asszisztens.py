from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ..adatmodellek.ai_asszisztens import AIAssistantRequest, AIAssistantResponse
from ..hitelesites import AccessToken, AuthenticatedUser, CsrfProtected, get_gateway
from ..hibak import ServiceUnavailableError
from ..jogosultsagok import ensure_project_access
from ..supabase_kapcsolat import SupabaseGateway
from ..szolgaltatasok.ai_provider import generate_ai_assistant_response


router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/assistant", response_model=AIAssistantResponse)
async def ai_assistant(
    payload: AIAssistantRequest,
    request: Request,
    token: AccessToken,
    _: AuthenticatedUser,
    __: CsrfProtected,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> AIAssistantResponse:
    if payload.project_id is not None:
        await ensure_project_access(gateway, token, payload.project_id)

    settings = request.app.state.settings
    if not settings.ai_configured:
        raise ServiceUnavailableError(
            "Az AI-asszisztens szolgáltatás jelenleg nincs beállítva."
        )

    result = await generate_ai_assistant_response(settings, payload)
    return AIAssistantResponse(
        answer=result.answer,
        sources=result.sources,
        request_id=secrets.token_urlsafe(12),
        suggestions=result.suggestions,
    )
