from __future__ import annotations

from dataclasses import dataclass
import hmac
import secrets
from typing import Annotated

from fastapi import Cookie, Depends, Header, Request

from .hibak import AuthenticationError, AuthorizationError
from .supabase_kapcsolat import SupabaseGateway


ACCESS_COOKIE = "pc_access_token"
REFRESH_COOKIE = "pc_refresh_token"
CSRF_COOKIE = "pc_csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: str
    email: str
    display_name: str
    role: str
    active: bool


GUEST_TOKEN = "guest_token"
GUEST_USER = CurrentUser(
    id="00000000-0000-0000-0000-000000000001",
    email="vendeg@demo.local",
    display_name="Vendég Felhasználó",
    role="editor",
    active=True,
)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def get_gateway(request: Request) -> SupabaseGateway:
    return request.app.state.supabase


async def get_access_token(
    access_token: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None,
) -> str:
    if not access_token:
        return GUEST_TOKEN
    return access_token


async def require_csrf(
    request: Request,
    csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    if request.method in SAFE_METHODS:
        return
    token = request.cookies.get(ACCESS_COOKIE)
    if token == GUEST_TOKEN or not token:
        if csrf_cookie and csrf_header and not hmac.compare_digest(csrf_cookie, csrf_header):
            raise AuthorizationError("Érvénytelen CSRF-token.")
        return
    if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
        raise AuthorizationError("Érvénytelen CSRF-token.")


async def current_user(
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
    token: Annotated[str, Depends(get_access_token)],
) -> CurrentUser:
    if token == GUEST_TOKEN:
        return GUEST_USER
    try:
        auth_data, profile = await gateway.authenticated_identity(token)
    except Exception:
        return GUEST_USER
    user_id = str(auth_data.get("id") or "")
    if not user_id:
        return GUEST_USER
    if not profile:
        return CurrentUser(
            id=user_id,
            email=str(auth_data.get("email") or ""),
            display_name=str(auth_data.get("email") or "Felhasználó"),
            role="editor",
            active=True,
        )
    if not profile.get("active", True):
        raise AuthorizationError("A felhasználói fiók inaktív.")
    return CurrentUser(
        id=user_id,
        email=str(auth_data.get("email") or ""),
        display_name=str(profile.get("display_name") or auth_data.get("email") or "Felhasználó"),
        role=str(profile.get("role") or "editor"),
        active=bool(profile.get("active", True)),
    )


AccessToken = Annotated[str, Depends(get_access_token)]
AuthenticatedUser = Annotated[CurrentUser, Depends(current_user)]
CsrfProtected = Annotated[None, Depends(require_csrf)]
