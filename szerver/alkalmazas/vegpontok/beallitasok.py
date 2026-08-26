from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from ..adatmodellek.beallitasok import (
    CalendarExceptionCreate,
    DailyRateUpsert,
    DisciplineVisibilityUpdate,
    OfferRequestSettingsUpsert,
    ProjectDataSheetMetadata,
    ProjectCompanyContactWrite,
    ProjectPhaseCreate,
    ScheduleKeyWrite,
)
from ..hitelesites import AccessToken, AuthenticatedUser, CsrfProtected, get_gateway
from ..hibak import NotFoundError
from ..jogosultsagok import ensure_project_access, require_permission
from ..supabase_kapcsolat import SupabaseGateway


router = APIRouter(prefix="/settings", tags=["settings"])


PROJECT_PROFILE_METADATA_KEYS = (
    "directorate",
    "project_role",
    "business_agreement",
    "project_scale",
    "project_source",
    "nationally_significant",
)


def _project_profile(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = {
        str(row.get("metadata_key") or ""): str(row.get("metadata_value") or "")
        for row in rows
    }
    return {
        "directorate": values.get("directorate", ""),
        "project_role": values.get("project_role", ""),
        "business_agreement": values.get("business_agreement", ""),
        "project_scale": values.get("project_scale", ""),
        "project_source": values.get("project_source", ""),
        "nationally_significant": values.get("nationally_significant", "false").lower() == "true",
    }


async def _optional_settings_rows(
    gateway: SupabaseGateway,
    table: str,
    token: str,
    **select_options: Any,
) -> list[dict[str, Any]]:
    try:
        result = await gateway.select(table, token, **select_options)
    except NotFoundError:
        return []
    return result.data


def _schedule_key_error(exc: NotFoundError) -> dict[str, str]:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    code = str(detail.get("code") or "HTTP 404")
    if code == "PGRST205":
        message = (
            "A PostgREST sémagyorsítótára nem látja a schedule_keys táblát. "
            "Ha a tábla az SQL Editorban létezik, a helyi backend valószínűleg "
            "másik Supabase projekthez kapcsolódik, vagy a sémagyorsítótár nem frissült."
        )
    else:
        message = (
            "A Supabase REST API nem tette elérhetővé a schedule_keys táblát. "
            "Az adatbázisban létező tábla önmagában nem igazolja, hogy a futó backend "
            "ugyanazt a Supabase projektet használja."
        )
    return {"code": code, "message": message}


async def _schedule_keys(
    gateway: SupabaseGateway,
    token: str,
) -> tuple[list[dict[str, Any]], bool, dict[str, str] | None]:
    try:
        result = await gateway.select("schedule_keys", token, order="is_active.desc,code.asc,id.asc")
    except NotFoundError as exc:
        return [], False, _schedule_key_error(exc)
    return result.data, True, None


@router.get("/{project_id}")
async def project_settings(
    project_id: int,
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> dict:
    await ensure_project_access(gateway, token, project_id)
    project, rates, phases, disciplines, exceptions, contract_sections, milestones, schedule_rows, offer_request, company_contacts, schedule_keys, project_profile = await asyncio.gather(
        gateway.select("projects", token, filters={"id": f"eq.{project_id}", "is_deleted": "eq.false"}, limit=1),
        gateway.select("project_daily_rates", token, filters={"project_id": f"eq.{project_id}"}, order="year.asc"),
        gateway.select("project_phases", token, filters={"project_id": f"eq.{project_id}"}, order="sort_order.asc,phase_name.asc"),
        gateway.select("project_disciplines", token, filters={"project_id": f"eq.{project_id}"}, order="sort_order.asc,name.asc"),
        gateway.select("calendar_exceptions", token, order="exception_date.desc"),
        gateway.select("project_contract_sections", token, filters={"project_id": f"eq.{project_id}"}, order="section_no.asc,id.asc"),
        gateway.select("project_milestones", token, filters={"project_id": f"eq.{project_id}"}, order="planned_date.asc,sequence_no.asc,id.asc"),
        gateway.select("schedule_rows", token, filters={"project_id": f"eq.{project_id}"}, order="position.asc,id.asc"),
        _optional_settings_rows(
            gateway,
            "project_offer_request_settings",
            token,
            filters={"project_id": f"eq.{project_id}"},
            limit=1,
        ),
        _optional_settings_rows(
            gateway,
            "project_company_contacts",
            token,
            filters={"project_id": f"eq.{project_id}"},
            order="display_order.asc,name.asc,id.asc",
        ),
        _schedule_keys(gateway, token),
        gateway.select(
            "contract_metadata",
            token,
            filters={
                "project_id": f"eq.{project_id}",
                "metadata_key": f"in.({','.join(PROJECT_PROFILE_METADATA_KEYS)})",
            },
            order="metadata_key.asc",
        ),
    )
    return {
        "project": project.data[0] if project.data else None,
        "daily_rates": rates.data,
        "phases": phases.data,
        "disciplines": disciplines.data,
        "calendar_exceptions": exceptions.data,
        "contract_sections": contract_sections.data,
        "milestones": milestones.data,
        "schedule_rows": schedule_rows.data,
        "schedule_keys": schedule_keys[0],
        "schedule_keys_available": schedule_keys[1],
        "schedule_keys_error": schedule_keys[2],
        "offer_request_settings": offer_request[0] if offer_request else {
            "project_id": project_id,
            "history": "",
            "task_description": "",
        },
        "company_contacts": company_contacts,
        "project_profile": _project_profile(project_profile.data),
    }


@router.post("/schedule-keys")
async def create_schedule_key(
    payload: ScheduleKeyWrite,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("master_data_admin")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    result = await gateway.insert("schedule_keys", token, payload.model_dump(mode="json"))
    return result[0]


@router.put("/schedule-keys/{key_id}")
async def update_schedule_key(
    key_id: int,
    payload: ScheduleKeyWrite,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("master_data_admin")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    result = await gateway.update("schedule_keys", token, payload.model_dump(mode="json"), {"id": f"eq.{key_id}"})
    if not result:
        raise NotFoundError("A jelkulcs nem található.")
    return result[0]


@router.delete("/schedule-keys/{key_id}")
async def delete_schedule_key(
    key_id: int,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("master_data_admin")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict[str, bool]:
    await gateway.delete("schedule_keys", token, {"id": f"eq.{key_id}"})
    return {"deleted": True}


@router.put("/{project_id}/offer-request")
async def save_offer_request_settings(
    project_id: int,
    payload: OfferRequestSettingsUpsert,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("project_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    await ensure_project_access(gateway, token, project_id, write=True)
    data = payload.model_dump(mode="json")
    data["project_id"] = project_id
    result = await gateway.upsert(
        "project_offer_request_settings",
        token,
        data,
        on_conflict="project_id",
    )
    return result[0]


@router.put("/{project_id}/project-profile")
async def save_project_profile(
    project_id: int,
    payload: ProjectDataSheetMetadata,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("project_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict[str, Any]:
    await ensure_project_access(gateway, token, project_id, write=True)
    values = payload.model_dump(mode="json")
    rows = [
        {
            "project_id": project_id,
            "metadata_key": key,
            "metadata_value": "true" if value is True else "false" if value is False else str(value),
        }
        for key, value in values.items()
    ]
    saved = await gateway.upsert(
        "contract_metadata",
        token,
        rows,
        on_conflict="project_id,metadata_key",
    )
    return _project_profile(saved)


@router.post("/{project_id}/company-contacts")
async def create_project_company_contact(
    project_id: int,
    payload: ProjectCompanyContactWrite,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("project_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    await ensure_project_access(gateway, token, project_id, write=True)
    data = payload.model_dump(mode="json")
    data["project_id"] = project_id
    result = await gateway.insert("project_company_contacts", token, data)
    return result[0]


@router.put("/{project_id}/company-contacts/{contact_id}")
async def update_project_company_contact(
    project_id: int,
    contact_id: int,
    payload: ProjectCompanyContactWrite,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("project_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    await ensure_project_access(gateway, token, project_id, write=True)
    result = await gateway.update(
        "project_company_contacts",
        token,
        payload.model_dump(mode="json"),
        {"id": f"eq.{contact_id}", "project_id": f"eq.{project_id}"},
    )
    if not result:
        raise NotFoundError("A céges kapcsolattartó nem található.")
    return result[0]


@router.delete("/{project_id}/company-contacts/{contact_id}")
async def delete_project_company_contact(
    project_id: int,
    contact_id: int,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("project_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict[str, bool]:
    await ensure_project_access(gateway, token, project_id, write=True)
    await gateway.delete(
        "project_company_contacts",
        token,
        {"id": f"eq.{contact_id}", "project_id": f"eq.{project_id}"},
    )
    return {"deleted": True}


@router.put("/{project_id}/daily-rates")
async def save_daily_rate(
    project_id: int,
    payload: DailyRateUpsert,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("discipline_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    await ensure_project_access(gateway, token, project_id, write=True)
    data = payload.model_dump(mode="json")
    data["project_id"] = project_id
    result = await gateway.upsert("project_daily_rates", token, data, on_conflict="project_id,year")
    return result[0]


@router.delete("/{project_id}/daily-rates/{rate_id}")
async def delete_daily_rate(
    project_id: int,
    rate_id: int,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("discipline_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict[str, bool]:
    await ensure_project_access(gateway, token, project_id, write=True)
    await gateway.delete("project_daily_rates", token, {"id": f"eq.{rate_id}", "project_id": f"eq.{project_id}"})
    return {"deleted": True}


@router.post("/{project_id}/phases")
async def create_project_phase(
    project_id: int,
    payload: ProjectPhaseCreate,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("discipline_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    await ensure_project_access(gateway, token, project_id, write=True)
    data = payload.model_dump(mode="json")
    data["project_id"] = project_id
    result = await gateway.insert("project_phases", token, data)
    return result[0]


@router.delete("/{project_id}/phases/{phase_id}")
async def delete_project_phase(
    project_id: int,
    phase_id: int,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("discipline_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict[str, bool]:
    await ensure_project_access(gateway, token, project_id, write=True)
    await gateway.delete("project_phases", token, {"id": f"eq.{phase_id}", "project_id": f"eq.{project_id}"})
    return {"deleted": True}


@router.patch("/{project_id}/disciplines/{discipline_id}")
async def update_discipline_visibility(
    project_id: int,
    discipline_id: int,
    payload: DisciplineVisibilityUpdate,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("discipline_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    await ensure_project_access(gateway, token, project_id, write=True)
    result = await gateway.update(
        "project_disciplines",
        token,
        payload.model_dump(mode="json"),
        {"id": f"eq.{discipline_id}", "project_id": f"eq.{project_id}"},
    )
    return result[0]


@router.post("/calendar-exceptions")
async def create_calendar_exception(
    payload: CalendarExceptionCreate,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("master_data_admin")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    result = await gateway.upsert(
        "calendar_exceptions",
        token,
        payload.model_dump(mode="json"),
        on_conflict="exception_date",
    )
    return result[0]


@router.delete("/calendar-exceptions/{exception_id}")
async def delete_calendar_exception(
    exception_id: int,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("master_data_admin")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict[str, bool]:
    await gateway.delete("calendar_exceptions", token, {"id": f"eq.{exception_id}"})
    return {"deleted": True}
