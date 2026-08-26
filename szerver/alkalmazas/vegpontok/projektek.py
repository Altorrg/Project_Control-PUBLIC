from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ..hitelesites import AccessToken, AuthenticatedUser, CsrfProtected, get_gateway
from ..hibak import ConflictError, NotFoundError, UpstreamError
from ..adatmodellek.projektek import ProjectCreate, ProjectUpdate
from ..jogosultsagok import require_permission
from ..supabase_kapcsolat import SupabaseGateway


router = APIRouter(prefix="/projects", tags=["projects"])


def _project_payload(project: dict) -> dict:
    payload = dict(project)
    payload.setdefault("contract_subject", None)
    for internal_field in (
        "creation_idempotency_key",
        "creation_request_fingerprint",
        "idempotency_key",
        "idempotency_fingerprint",
    ):
        payload.pop(internal_field, None)
    return payload


@router.get("")
async def list_projects(
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
    search: str = Query(default="", max_length=120),
) -> list[dict]:
    filters = {"is_deleted": "eq.false"}
    if search.strip():
        safe = (
            search.strip()
            .replace(",", " ")
            .replace("(", " ")
            .replace(")", " ")
            .replace("*", " ")
        )
        filters["or"] = (
            f"(name.ilike.*{safe}*,work_number.ilike.*{safe}*,"
            f"responsible_company.ilike.*{safe}*,main_customer.ilike.*{safe}*,"
            f"customer.ilike.*{safe}*)"
        )
    result = await gateway.select(
        "projects",
        token,
        filters=filters,
        order="name.asc,id.asc",
    )
    return [_project_payload(project) for project in result.data]


@router.get("/actionable-gaps")
async def actionable_gaps(
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> list[dict]:
    """Return existing open checks and notifications in one RLS-filtered portfolio list."""
    result = await gateway.rpc("current_actionable_gaps", token)
    rows = result if isinstance(result, list) else []
    return sorted(
        rows,
        key=lambda item: (
            int(item.get("priority") or 9),
            str(item.get("relevant_date") or "9999-12-31"),
            str(item.get("project_name") or "").casefold(),
            str(item.get("gap_key") or ""),
        ),
    )


@router.get("/{project_id}")
async def get_project(
    project_id: int,
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> dict:
    result = await gateway.select(
        "projects",
        token,
        filters={"id": f"eq.{project_id}", "is_deleted": "eq.false"},
        limit=1,
    )
    if not result.data:
        raise NotFoundError("A projekt nem található.")
    return _project_payload(result.data[0])


@router.post("")
async def create_project(
    payload: ProjectCreate,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("project_create")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    data = payload.model_dump(mode="json")
    if data["idempotency_key"] is None:
        data.pop("idempotency_key")
    if data["contract_subject"] is None:
        data.pop("contract_subject")
    result = await gateway.rpc("create_project", token, {"payload": data})
    project = result[0] if isinstance(result, list) and result else result
    if not isinstance(project, dict) or not project.get("id"):
        raise UpstreamError("A projekt létrehozása nem adott vissza megnyitható projektet.")
    return _project_payload(project)


@router.patch("/{project_id}")
async def update_project(
    project_id: int,
    payload: ProjectUpdate,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("project_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    data = payload.model_dump(mode="json", exclude_unset=True)
    if "contract_value" in data:
        sections = await gateway.select(
            "project_contract_sections",
            token,
            filters={"project_id": f"eq.{project_id}"},
            limit=1,
        )
        if sections.data:
            raise ConflictError(
                "A szerződéses érték a főszerződéses szakaszokból származik. Az Ütemterv szerződéses mérföldköveinél módosítható."
            )
    result = await gateway.rpc(
        "update_project",
        token,
        {"target_project_id": project_id, "payload": data},
    )
    project = result[0] if isinstance(result, list) and result else result
    return _project_payload(project)


@router.delete("/{project_id}")
async def archive_project(
    project_id: int,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("project_delete")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict[str, bool]:
    await gateway.rpc("archive_project", token, {"target_project_id": project_id})
    return {"archived": True}
