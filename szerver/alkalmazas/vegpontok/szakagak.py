from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ..hitelesites import AccessToken, AuthenticatedUser, CsrfProtected, get_gateway
from ..adatmodellek.szakagak import DailyProgressUpsert, ProjectDisciplineCreate
from ..jogosultsagok import require_permission
from ..supabase_kapcsolat import SupabaseGateway


router = APIRouter(prefix="/disciplines", tags=["disciplines"])


@router.get("/{project_id}")
async def list_disciplines(project_id: int, token: AccessToken, _: AuthenticatedUser, gateway: Annotated[SupabaseGateway, Depends(get_gateway)]) -> list[dict]:
    result = await gateway.select("project_disciplines", token, filters={"project_id": f"eq.{project_id}"}, order="sort_order.asc,name.asc")
    return result.data


@router.post("")
async def create_discipline(payload: ProjectDisciplineCreate, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("discipline_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict:
    result = await gateway.insert("project_disciplines", token, payload.model_dump(mode="json"))
    return result[0]


@router.get("/{project_id}/daily-progress")
async def daily_progress(project_id: int, token: AccessToken, _: AuthenticatedUser, gateway: Annotated[SupabaseGateway, Depends(get_gateway)]) -> list[dict]:
    result = await gateway.select("daily_progress", token, filters={"project_id": f"eq.{project_id}"}, order="record_date.asc,discipline_name.asc")
    return result.data


@router.get("/{project_id}/phases")
async def project_phases(project_id: int, token: AccessToken, _: AuthenticatedUser, gateway: Annotated[SupabaseGateway, Depends(get_gateway)]) -> list[dict]:
    result = await gateway.select("project_phases", token, filters={"project_id": f"eq.{project_id}"}, order="sort_order.asc,phase_name.asc")
    return result.data


@router.get("/{project_id}/daily-rates")
async def project_daily_rates(project_id: int, token: AccessToken, _: AuthenticatedUser, gateway: Annotated[SupabaseGateway, Depends(get_gateway)]) -> list[dict]:
    result = await gateway.select("project_daily_rates", token, filters={"project_id": f"eq.{project_id}"}, order="year.asc")
    return result.data


@router.put("/{project_id}/daily-progress")
async def upsert_daily_progress(project_id: int, payload: DailyProgressUpsert, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("discipline_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict:
    data = payload.model_dump(mode="json")
    data["project_id"] = project_id
    result = await gateway.upsert("daily_progress", token, data, on_conflict="project_id,discipline_name,record_date")
    return result[0]


@router.put("/{project_id}/daily-progress/{row_id}")
async def update_daily_progress(project_id: int, row_id: int, payload: DailyProgressUpsert, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("discipline_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict:
    data = payload.model_dump(mode="json")
    data["project_id"] = project_id
    result = await gateway.update("daily_progress", token, data, {"id": f"eq.{row_id}", "project_id": f"eq.{project_id}"})
    return result[0]


@router.delete("/{project_id}/daily-progress/{row_id}")
async def delete_daily_progress(project_id: int, row_id: int, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("discipline_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict[str, bool]:
    await gateway.delete("daily_progress", token, {"id": f"eq.{row_id}", "project_id": f"eq.{project_id}"})
    return {"deleted": True}


@router.post("/{project_id}/months/{month}")
async def add_month(project_id: int, month: str, token: AccessToken, _: CsrfProtected, phase: str = "", __=Depends(require_permission("discipline_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> list[dict]:
    return await gateway.rpc("add_daily_progress_month", token, {"target_project_id": project_id, "month_value": month, "phase_value": phase}) or []


@router.delete("/{project_id}/months/{month}")
async def delete_month(project_id: int, month: str, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("discipline_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict[str, bool]:
    await gateway.delete("daily_progress", token, {"project_id": f"eq.{project_id}", "record_date": f"eq.{month}"})
    return {"deleted": True}
