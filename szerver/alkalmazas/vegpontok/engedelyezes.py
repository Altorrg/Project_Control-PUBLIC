from __future__ import annotations

from pathlib import Path
import re
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from ..hitelesites import AccessToken, AuthenticatedUser, CsrfProtected, get_gateway
from ..hibak import AppError, NotFoundError
from ..adatmodellek.engedelyezes import (
    ApprovalDecision,
    AssignmentCreate,
    AssignmentUpdate,
    EventRoundCreate,
    EventRoundUpdate,
    PartnerChangeCreate,
)
from ..jogosultsagok import require_permission
from ..szolgaltatasok.adatcsere import build_engagement_excel, build_engagement_pdf, parse_engagement_workbook
from ..supabase_kapcsolat import SupabaseGateway


router = APIRouter(prefix="/engagements", tags=["engagements"])
ALLOWED_ATTACHMENT_EXTENSIONS = {".pdf", ".xlsx", ".xlsm", ".docx", ".jpg", ".jpeg", ".png"}
ALLOWED_ATTACHMENT_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroenabled.12",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/jpeg",
    "image/png",
}


@router.post("/import/preview")
async def preview_import(
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("eng_admin")),
    file: UploadFile = File(...),
) -> dict:
    content = await file.read(15 * 1024 * 1024 + 1)
    try:
        return parse_engagement_workbook(content, file.filename or "import.xlsx")
    except ValueError as exc:
        raise AppError(str(exc)) from exc


@router.post("/import/{project_id}")
async def commit_import(
    project_id: int,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("eng_admin")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
    file: UploadFile = File(...),
) -> dict:
    content = await file.read(15 * 1024 * 1024 + 1)
    try:
        parsed = parse_engagement_workbook(content, file.filename or "import.xlsx")
    except ValueError as exc:
        raise AppError(str(exc)) from exc
    if parsed["errors"]:
        raise AppError("Az import javítandó hibákat tartalmaz.", detail=parsed["errors"][:100])
    result = await gateway.rpc("import_engagement_workbook", token, {"target_project_id": project_id, "payload": parsed})
    return result or {}


@router.get("/export/{project_id}.xlsx")
async def export_excel(project_id: int, token: AccessToken, _: AuthenticatedUser, gateway: Annotated[SupabaseGateway, Depends(get_gateway)]) -> Response:
    data = await gateway.rpc("export_engagement_project", token, {"target_project_id": project_id})
    content = build_engagement_excel(data or {})
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="engedelyek-{project_id}.xlsx"'})


@router.get("/export/{project_id}.pdf")
async def export_pdf(project_id: int, token: AccessToken, _: AuthenticatedUser, gateway: Annotated[SupabaseGateway, Depends(get_gateway)]) -> Response:
    data = await gateway.rpc("export_engagement_project", token, {"target_project_id": project_id})
    content = build_engagement_pdf(data or {})
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="engedelyek-{project_id}.pdf"'})


@router.get("/master-data")
async def master_data(
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> dict[str, list[dict]]:
    statuses = await gateway.select("eng_statuses", token, order="priority.asc,code.asc")
    tasks = await gateway.select("eng_tasks", token, filters={"active": "eq.true"}, order="sort_order.asc,name.asc")
    interventions = await gateway.select("eng_intervention_types", token, filters={"active": "eq.true"}, order="name.asc")
    return {"statuses": statuses.data, "tasks": tasks.data, "intervention_types": interventions.data}


@router.get("/disciplines/{project_id}")
async def engagement_disciplines(
    project_id: int,
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> list[dict]:
    result = await gateway.select(
        "eng_disciplines",
        token,
        filters={"project_id": f"eq.{project_id}"},
        order="sort_order.asc,name.asc,id.asc",
    )
    return result.data


@router.get("/dashboard/{project_id}")
async def dashboard(
    project_id: int,
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
    warning_days: int = Query(default=14, ge=1, le=365),
) -> dict:
    result = await gateway.rpc(
        "engagement_dashboard",
        token,
        {"target_project_id": project_id, "warning_days": warning_days},
    )
    return result or {}


@router.get("/assignments")
async def list_assignments(
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
    project_id: int,
    search: str = Query(default="", max_length=255),
    discipline_id: int | None = None,
    task_id: int | None = None,
    status_code: str | None = Query(default=None, max_length=10),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    result = await gateway.rpc(
        "search_engagement_assignments",
        token,
        {
            "target_project_id": project_id,
            "search_text": search.strip(),
            "filter_discipline_id": discipline_id,
            "filter_task_id": task_id,
            "filter_status_code": status_code,
            "page_limit": limit,
            "page_offset": offset,
        },
    )
    items = result or []
    total = int(items[0].get("total_count", len(items))) if items else 0
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/assignments/{assignment_id}")
async def get_assignment(
    assignment_id: int,
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> dict:
    result = await gateway.rpc("engagement_assignment_detail", token, {"target_assignment_id": assignment_id})
    if not result:
        raise NotFoundError("Az engedélyezési ügy nem található.")
    return result[0] if isinstance(result, list) else result


@router.post("/assignments")
async def create_assignment(
    payload: AssignmentCreate,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("eng_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    result = await gateway.rpc("create_engagement_assignment", token, {"payload": payload.model_dump(mode="json")})
    return result[0] if isinstance(result, list) and result else result


@router.patch("/assignments/{assignment_id}")
async def update_assignment(
    assignment_id: int,
    payload: AssignmentUpdate,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("eng_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    result = await gateway.rpc(
        "update_engagement_assignment",
        token,
        {"target_assignment_id": assignment_id, "payload": payload.model_dump(mode="json", exclude_unset=True)},
    )
    return result[0] if isinstance(result, list) and result else result


@router.delete("/assignments/{assignment_id}")
async def archive_assignment(
    assignment_id: int,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("eng_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict[str, bool]:
    await gateway.rpc("archive_engagement_assignment", token, {"target_assignment_id": assignment_id})
    return {"archived": True}


@router.post("/assignments/{assignment_id}/rounds")
async def create_round(
    assignment_id: int,
    payload: EventRoundCreate,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("eng_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    result = await gateway.rpc(
        "create_engagement_round",
        token,
        {"target_assignment_id": assignment_id, "payload": payload.model_dump(mode="json")},
    )
    return result[0] if isinstance(result, list) and result else result


@router.patch("/rounds/{round_id}")
async def update_round(
    round_id: int,
    payload: EventRoundUpdate,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("eng_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    result = await gateway.rpc(
        "update_engagement_round",
        token,
        {"target_round_id": round_id, "payload": payload.model_dump(mode="json")},
    )
    return result[0] if isinstance(result, list) and result else result


@router.delete("/rounds/{round_id}")
async def delete_round(
    round_id: int,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("eng_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict[str, bool]:
    await gateway.rpc("delete_engagement_round", token, {"target_round_id": round_id})
    return {"deleted": True}


@router.get("/partners")
async def search_partners(
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
    search: str = Query(default="", max_length=255),
    org_type: str = Query(default="", max_length=120),
    include_pending: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    return await gateway.rpc(
        "search_engagement_partners",
        token,
        {"search_text": search, "filter_org_type": org_type, "include_pending": include_pending, "page_limit": limit},
    ) or []


@router.post("/partner-requests")
async def propose_partner_change(
    payload: PartnerChangeCreate,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("eng_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    result = await gateway.rpc("propose_partner_change", token, {"payload": payload.model_dump(mode="json")})
    return result[0] if isinstance(result, list) and result else result


@router.get("/partner-requests")
async def list_partner_requests(
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
    status: str = Query(default="pending", max_length=40),
) -> list[dict]:
    result = await gateway.select(
        "eng_partner_change_requests",
        token,
        filters={"status": f"eq.{status}"} if status else None,
        order="created_at.desc,id.desc",
    )
    return result.data


@router.post("/partner-requests/{request_id}/decision")
async def review_partner_request(
    request_id: int,
    payload: ApprovalDecision,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("eng_admin")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    result = await gateway.rpc(
        "review_partner_change_request",
        token,
        {"target_request_id": request_id, "decision_payload": payload.model_dump(mode="json")},
    )
    return result[0] if isinstance(result, list) and result else result


@router.post("/assignments/{assignment_id}/attachments")
async def upload_attachment(
    assignment_id: int,
    request: Request,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("eng_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
    file: UploadFile = File(...),
    note: str = Form(default=""),
) -> dict:
    original_name = Path(file.filename or "fajl").name
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_ATTACHMENT_EXTENSIONS or file.content_type not in ALLOWED_ATTACHMENT_MIME:
        raise AppError("Nem engedélyezett csatolmánytípus.")
    content = await file.read(request.app.state.settings.max_upload_bytes + 1)
    if len(content) > request.app.state.settings.max_upload_bytes:
        raise AppError("A csatolmány nagyobb a megengedett méretnél.")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", original_name)[:180]
    object_path = f"assignments/{assignment_id}/{uuid4().hex}-{safe_name}"
    await gateway.upload("engagement-attachments", object_path, token, content, file.content_type)
    result = await gateway.rpc(
        "register_engagement_attachment",
        token,
        {
            "target_assignment_id": assignment_id,
            "object_path": object_path,
            "original_name": original_name,
            "content_type": file.content_type,
            "size_bytes": len(content),
            "note": note[:2000],
        },
    )
    return result[0] if isinstance(result, list) and result else result


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(
    attachment_id: int,
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> RedirectResponse:
    result = await gateway.select(
        "eng_attachments",
        token,
        filters={"id": f"eq.{attachment_id}"},
        limit=1,
    )
    if not result.data:
        raise NotFoundError("A csatolmány nem található vagy nincs hozzá jogosultságod.")
    url = await gateway.signed_download_url(
        "engagement-attachments",
        result.data[0]["storage_path"],
        token,
    )
    return RedirectResponse(url=url, status_code=307)
