from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from ..hitelesites import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    REFRESH_COOKIE,
    AuthenticatedUser,
    CsrfProtected,
    CurrentUser,
    get_gateway,
    AccessToken,
    new_csrf_token,
)
from ..adatmodellek.hitelesites import LoginRequest, PasswordChangeRequest
from ..hibak import AuthenticationError, UpstreamError
from ..jogosultsagok import has_permission
from ..supabase_kapcsolat import SupabaseGateway


router = APIRouter(prefix="/auth", tags=["authentication"])


def _set_session_cookies(response: Response, request: Request, session: dict, csrf: str) -> None:
    settings = request.app.state.settings
    common = {
        "secure": settings.cookie_secure,
        "httponly": True,
        "samesite": "lax",
        "path": "/",
    }
    response.set_cookie(
        ACCESS_COOKIE,
        session["access_token"],
        max_age=int(session.get("expires_in") or 3600),
        **common,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        session["refresh_token"],
        max_age=60 * 60 * 24 * 30,
        **common,
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=60 * 60 * 24 * 30,
        secure=settings.cookie_secure,
        httponly=False,
        samesite="lax",
        path="/",
    )


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> dict[str, object]:
    session = await gateway.sign_in(str(payload.email), payload.password)
    csrf = new_csrf_token()
    _set_session_cookies(response, request, session, csrf)
    return {"authenticated": True, "csrf_token": csrf, "expires_in": session.get("expires_in", 3600)}


@router.post("/guest")
async def guest_login(request: Request, response: Response) -> dict[str, object]:
    csrf = new_csrf_token()
    session = {
        "access_token": "guest_token",
        "refresh_token": "",
        "expires_in": 60 * 60 * 24 * 365,
    }
    _set_session_cookies(response, request, session, csrf)
    return {
        "authenticated": True,
        "csrf_token": csrf,
        "role": "editor",
        "display_name": "Vendég Felhasználó",
        "expires_in": session["expires_in"],
    }


@router.post("/refresh")
async def refresh(request: Request, response: Response) -> dict[str, object]:
    refresh_token = request.cookies.get(REFRESH_COOKIE, "")
    if not refresh_token:
        return {"authenticated": False}
    session = await request.app.state.supabase.refresh_session(refresh_token)
    csrf = request.cookies.get(CSRF_COOKIE) or new_csrf_token()
    _set_session_cookies(response, request, session, csrf)
    return {"authenticated": True, "csrf_token": csrf, "expires_in": session.get("expires_in", 3600)}


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    for name in (ACCESS_COOKIE, REFRESH_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/")
    return {"authenticated": False}


@router.post("/change-password")
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    user: AuthenticatedUser,
    _: CsrfProtected,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> dict[str, object]:
    try:
        verified_session = await gateway.sign_in(user.email, payload.current_password)
    except UpstreamError as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        code = str(detail.get("code") or detail.get("error_code") or "").lower()
        message = str(detail.get("message") or detail.get("error_description") or "").lower()
        if code in {"invalid_credentials", "invalid_grant"} or "invalid login" in message:
            raise AuthenticationError("A jelenlegi jelszó hibás.") from exc
        raise

    verified_user = verified_session.get("user") or {}
    if str(verified_user.get("id") or "") != user.id:
        raise AuthenticationError("A jelenlegi jelszó ellenőrzése sikertelen.")

    verified_token = str(verified_session.get("access_token") or "")
    if not verified_token:
        raise AuthenticationError("A jelenlegi jelszó ellenőrzése sikertelen.")

    await gateway.update_password(
        verified_token,
        payload.current_password,
        payload.new_password,
    )
    renewed_session = await gateway.sign_in(user.email, payload.new_password)
    csrf = new_csrf_token()
    _set_session_cookies(response, request, renewed_session, csrf)
    return {
        "changed": True,
        "csrf_token": csrf,
        "expires_in": renewed_session.get("expires_in", 3600),
    }


@router.get("/me")
async def me(user: AuthenticatedUser, token: AccessToken, gateway: Annotated[SupabaseGateway, Depends(get_gateway)]) -> dict[str, object]:
    permission_keys = (
        "project_create", "project_write", "project_delete", "admin_panel",
        "discipline_write", "schedule_write", "subcontractor_write", "finance_write",
        "eng_write", "eng_admin", "master_data_admin", "arbevetel",
    )
    permission_values = await asyncio.gather(*(has_permission(gateway, token, key) for key in permission_keys))
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "active": user.active,
        "permissions": dict(zip(permission_keys, permission_values, strict=True)),
    }
