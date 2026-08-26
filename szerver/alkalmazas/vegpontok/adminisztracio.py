from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import Field

from ..hitelesites import AccessToken, AuthenticatedUser, CsrfProtected, get_gateway
from ..adatmodellek.kozos import ApiModel
from ..jogosultsagok import require_permission
from ..supabase_kapcsolat import SupabaseGateway


router = APIRouter(prefix="/admin", tags=["admin"])


class ProfileUpdate(ApiModel):
    display_name: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, max_length=80)
    active: bool | None = None


class ProjectMembership(ApiModel):
    profile_id: UUID
    project_id: int
    can_write: bool = True


class ApplicationClockUpdate(ApiModel):
    offset_days: int = Field(default=0, ge=-3650, le=3650)
    force_first_of_month: bool = False


@router.get("/profiles")
async def profiles(token: AccessToken, _: AuthenticatedUser, __=Depends(require_permission("admin_panel")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> list[dict]:
    result = await gateway.select("profiles", token, order="display_name.asc")
    return result.data


@router.patch("/profiles/{profile_id}")
async def update_profile(profile_id: UUID, payload: ProfileUpdate, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("admin_panel")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict:
    result = await gateway.update("profiles", token, payload.model_dump(mode="json", exclude_unset=True), {"id": f"eq.{profile_id}"})
    return result[0]


@router.put("/project-memberships")
async def set_membership(payload: ProjectMembership, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("admin_panel")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict:
    result = await gateway.upsert("project_memberships", token, payload.model_dump(mode="json"), on_conflict="profile_id,project_id")
    return result[0]


@router.get("/application-clock")
async def application_clock(
    token: AccessToken,
    user: AuthenticatedUser,
    __=Depends(require_permission("admin_panel")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    offset_key = f"time_offset_days:{user.id}"
    first_of_month_key = f"force_first_of_month:{user.id}"
    settings = await gateway.select(
        "app_settings",
        token,
        filters={"setting_key": f"in.({offset_key},{first_of_month_key})"},
    )
    values = {row["setting_key"]: row.get("setting_value") for row in settings.data}
    application_date = await gateway.rpc("app_today", token)
    return {
        "system_date": date.today().isoformat(),
        "application_date": application_date,
        "offset_days": int(values.get(offset_key) or 0),
        "force_first_of_month": bool(values.get(first_of_month_key) or False),
    }


@router.put("/application-clock")
async def update_application_clock(
    payload: ApplicationClockUpdate,
    token: AccessToken,
    _: CsrfProtected,
    user: AuthenticatedUser,
    __=Depends(require_permission("admin_panel")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    offset_key = f"time_offset_days:{user.id}"
    first_of_month_key = f"force_first_of_month:{user.id}"
    await gateway.upsert(
        "app_settings",
        token,
        [
            {"setting_key": offset_key, "setting_value": payload.offset_days, "updated_by": user.id},
            {"setting_key": first_of_month_key, "setting_value": payload.force_first_of_month, "updated_by": user.id},
        ],
        on_conflict="setting_key",
    )
    return await application_clock(token, user, __, gateway)
