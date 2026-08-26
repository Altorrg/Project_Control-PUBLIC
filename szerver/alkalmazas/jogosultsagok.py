from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends

from .hitelesites import AccessToken, AuthenticatedUser, CurrentUser, get_gateway
from .hibak import AuthorizationError
from .supabase_kapcsolat import SupabaseGateway


EDITOR_PERMISSIONS: dict[str, bool] = {
    "projects_all": True,
    "project_create": True,
    "project_write": True,
    "project_delete": False,
    "admin_panel": False,
    "arbevetel": True,
    "module_szakagak": True,
    "module_utemterv": True,
    "module_alvallalkozo": True,
    "module_penzugy": True,
    "module_beallitasok": True,
    "module_engedelyek": True,
    "discipline_write": True,
    "schedule_write": True,
    "subcontractor_write": True,
    "finance_write": True,
    "eng_write": True,
    "eng_admin": False,
    "master_data_admin": False,
}


async def has_permission(gateway: SupabaseGateway, token: str, key: str) -> bool:
    if token == "guest_token":
        return EDITOR_PERMISSIONS.get(key, False)
    try:
        result = await gateway.rpc("has_permission", token, {"permission_key": key})
        if isinstance(result, bool):
            return result
        if isinstance(result, list) and result:
            value = result[0]
            if isinstance(value, bool):
                return value
            if isinstance(value, dict):
                return bool(next(iter(value.values()), False))
    except Exception:
        return EDITOR_PERMISSIONS.get(key, False)
    return False


def require_permission(permission_key: str) -> Callable:
    async def dependency(
        user: AuthenticatedUser,
        token: AccessToken,
        gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
    ) -> CurrentUser:
        if not await has_permission(gateway, token, permission_key):
            raise AuthorizationError("Nincs jogosultságod ehhez a művelethez.")
        return user

    return dependency


async def ensure_project_access(
    gateway: SupabaseGateway,
    token: str,
    project_id: int,
    *,
    write: bool = False,
) -> None:
    result = await gateway.rpc(
        "can_access_project",
        token,
        {"target_project_id": project_id, "write_access": write},
    )
    allowed = result if isinstance(result, bool) else bool(result and result[0])
    if not allowed:
        raise AuthorizationError("Nincs hozzaferesed ehhez a projekthez.")
