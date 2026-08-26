from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from ..adatmodellek.utemterv import (
    ContractSectionWrite,
    ProjectMilestoneWrite,
    ScheduleCalculationRequest,
    ScheduleReorderRequest,
    ScheduleRowCreate,
    ScheduleSettingsWrite,
)
from ..hibak import ConflictError, NotFoundError
from ..hitelesites import AccessToken, AuthenticatedUser, CsrfProtected, get_gateway
from ..jogosultsagok import require_permission
from ..szolgaltatasok.utemterv import (
    FIXED_DATE,
    MILESTONE_LINKED_DATE,
    SCHEDULE_LINKED_DATE,
    build_schedule_workbook,
    calculate_milestone_dates,
    calculate_schedule,
    is_workday,
    normalize_milestone,
)
from ..supabase_kapcsolat import SupabaseGateway


router = APIRouter(prefix="/schedules", tags=["schedules"])
PROJECT_START_LABEL = "Projekt kezdete"
PROJECT_START_PHASE = "INDULÁS"


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value


def _milestone_write_data(
    payload: ProjectMilestoneWrite,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = payload.model_dump(mode="json")
    if previous is not None:
        previous_normalized = normalize_milestone(previous)
        supplied = payload.model_fields_set
        if "short_name" not in supplied:
            data["short_name"] = previous_normalized["short_name"]
        if "official_name" not in supplied:
            data["official_name"] = (
                data["name"] if "name" in supplied else previous_normalized["official_name"]
            )
        if "description" not in supplied:
            data["description"] = previous_normalized["description"]
        if "schedule_row_id" not in supplied:
            data["schedule_row_id"] = previous_normalized["schedule_row_id"]
        if "reference_name" not in supplied:
            data["reference_name"] = previous_normalized.get("reference_name") or ""
    data["name"] = data["official_name"]
    return data


async def _sync_project_contract_value(project_id: int, token: str, gateway: SupabaseGateway) -> Decimal:
    sections = await gateway.select(
        "project_contract_sections",
        token,
        filters={"project_id": f"eq.{project_id}"},
    )
    total = sum(
        (
            Decimal(str(row.get("modified_fee") or 0))
            or Decimal(str(row.get("original_fee") or 0))
        )
        for row in sections.data
    )
    await gateway.rpc(
        "update_project",
        token,
        {"target_project_id": project_id, "payload": {"contract_value": str(total)}},
    )
    return total


async def _project_start(project_id: int, token: str, gateway: SupabaseGateway) -> date:
    result = await gateway.select(
        "schedule_entries",
        token,
        filters={"project_id": f"eq.{project_id}", "phase": f"eq.{PROJECT_START_PHASE}"},
        limit=1,
    )
    if result.data:
        return date.fromisoformat(str(result.data[0]["entry_date"])[:10])
    return date.today()


async def _calendar_exceptions(token: str, gateway: SupabaseGateway) -> tuple[set[date], set[date]]:
    exceptions = await gateway.select("calendar_exceptions", token)
    workdays: set[date] = set()
    holidays: set[date] = set()
    for item in exceptions.data:
        target = date.fromisoformat(str(item["exception_date"])[:10])
        (workdays if item["exception_type"] == "Munkanap" else holidays).add(target)
    return workdays, holidays


async def _timeline(
    project_id: int,
    token: str,
    gateway: SupabaseGateway,
    project_start: date | None = None,
    financial_phase_no: int | None = None,
) -> dict[str, Any]:
    start = project_start or await _project_start(project_id, token, gateway)
    milestones = await gateway.select(
        "project_milestones",
        token,
        filters={"project_id": f"eq.{project_id}"},
        order="phase_no.asc,sequence_no.asc,id.asc",
    )
    try:
        calculated = await _calculated_schedule(project_id, token, gateway, start)
        calculated_milestones = calculate_milestone_dates(milestones.data, calculated)
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    if financial_phase_no is not None:
        visible_rows = [
            row
            for row in calculated
            if row.get("financial_phase_no") is not None
            and int(row["financial_phase_no"]) == financial_phase_no
        ]
        visible_milestones = [
            item for item in calculated_milestones
            if int(item.get("phase_no") or 0) == financial_phase_no
        ]
    else:
        visible_rows = calculated
        visible_milestones = calculated_milestones
    dated = [row["start_date"] for row in visible_rows] + [row["end_date"] for row in visible_rows]
    dated += [item["planned_date"] for item in visible_milestones if item.get("planned_date")]
    range_start = min(dated, default=start) - timedelta(days=2)
    range_end = max(dated, default=start) + timedelta(days=5)
    extra_workdays, extra_holidays = await _calendar_exceptions(token, gateway)
    non_working_days: list[str] = []
    cursor = range_start
    while cursor <= range_end:
        if not is_workday(cursor, extra_workdays, extra_holidays):
            non_working_days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return {
        "project_start": start.isoformat(),
        "non_working_days": non_working_days,
        "financial_phase_no": financial_phase_no,
        "rows": [{key: _iso(value) for key, value in row.items()} for row in visible_rows],
        "milestones": [
            {key: _iso(value) for key, value in milestone.items()}
            for milestone in visible_milestones
        ],
    }


async def _calculated_schedule(
    project_id: int,
    token: str,
    gateway: SupabaseGateway,
    project_start: date | None = None,
) -> list[dict[str, Any]]:
    start = project_start or await _project_start(project_id, token, gateway)
    rows = await gateway.select(
        "schedule_rows", token, filters={"project_id": f"eq.{project_id}"}, order="position.asc,id.asc"
    )
    workdays, holidays = await _calendar_exceptions(token, gateway)
    return calculate_schedule(
        rows.data,
        start,
        extra_workdays=workdays,
        extra_holidays=holidays,
    )


async def _refresh_dynamic_milestones(project_id: int, token: str, gateway: SupabaseGateway) -> list[dict]:
    timeline = await _timeline(project_id, token, gateway)
    for milestone in timeline["milestones"]:
        date_type = str(milestone.get("date_type") or FIXED_DATE)
        if date_type not in {SCHEDULE_LINKED_DATE, MILESTONE_LINKED_DATE}:
            continue
        await gateway.update(
            "project_milestones",
            token,
            {"planned_date": milestone.get("planned_date")},
            {"id": f"eq.{milestone['id']}", "project_id": f"eq.{project_id}"},
        )
    return timeline["milestones"]


async def _reopen_revenue_payment(
    project_id: int, milestone_id: int, token: str, gateway: SupabaseGateway
) -> None:
    payments = await gateway.select(
        "payments",
        token,
        filters={
            "project_id": f"eq.{project_id}",
            "reference": f"eq.BEV_MS_{milestone_id}",
            "status": "eq.Pénzügyileg teljesítve",
        },
    )
    for payment in payments.data:
        await gateway.update(
            "payments",
            token,
            {"status": "Várható", "payment_date": None},
            {"id": f"eq.{payment['id']}", "project_id": f"eq.{project_id}"},
        )


async def _phase_milestones(
    project_id: int, phase_no: int, token: str, gateway: SupabaseGateway
) -> list[dict]:
    result = await gateway.select(
        "project_milestones",
        token,
        filters={"project_id": f"eq.{project_id}", "phase_no": f"eq.{phase_no}"},
    )
    return result.data


async def _validate_schedule_row(
    project_id: int,
    payload: ScheduleRowCreate,
    token: str,
    gateway: SupabaseGateway,
    row_id: int | None = None,
) -> None:
    rows = await gateway.select("schedule_rows", token, filters={"project_id": f"eq.{project_id}"})
    sections = await gateway.select(
        "project_contract_sections", token, filters={"project_id": f"eq.{project_id}"}
    )
    available_phase_numbers = {int(item["section_no"]) for item in sections.data}
    if payload.financial_phase_no is not None and payload.financial_phase_no not in available_phase_numbers:
        raise ConflictError("A kiválasztott pénzügyi fázis nem ehhez a projekthez tartozik.")
    if row_id is None and available_phase_numbers and payload.financial_phase_no is None:
        raise ConflictError("Az új ütemtervi elemhez pénzügyi fázist kell választani.")

    if payload.schedule_key_id is not None:
        try:
            key = await gateway.select(
                "schedule_keys", token, filters={"id": f"eq.{payload.schedule_key_id}"}, limit=1
            )
        except NotFoundError as exc:
            raise ConflictError("A jelkulcs-törzs még nincs telepítve.") from exc
        if not key.data:
            raise ConflictError("A kiválasztott jelkulcs nem található.")
        payload.phase_code = str(key.data[0].get("code") or "").strip() or None
    elif payload.phase_code:
        try:
            key = await gateway.select(
                "schedule_keys",
                token,
                filters={"code_key": f"eq.{payload.phase_code.strip().casefold()}"},
                limit=1,
            )
        except NotFoundError:
            key = None
        if key and key.data:
            payload.schedule_key_id = int(key.data[0]["id"])
    same_name = next(
        (
            row
            for row in rows.data
            if int(row["id"]) != int(row_id or 0)
            and str(row.get("phase_name") or "").strip().casefold() == payload.phase_name.strip().casefold()
        ),
        None,
    )
    if same_name:
        raise ConflictError("Ezzel a névvel már létezik ütemtervi elem. A függőségekhez egyedi megnevezés szükséges.")
    if payload.reference_name == PROJECT_START_LABEL:
        return
    reference = next(
        (
            row
            for row in rows.data
            if int(row["id"]) != int(row_id or 0)
            and str(row.get("phase_name") or "").strip() == payload.reference_name.strip()
        ),
        None,
    )
    if reference is None:
        raise ConflictError("A hivatkozott ütemtervi elem nem található.")
    reference_phase = reference.get("financial_phase_no")
    if payload.financial_phase_no is not None and (
        reference_phase is None or int(reference_phase) != payload.financial_phase_no
    ):
        raise ConflictError("Egy pénzügyi fázis ütemtervi eleme csak ugyanazon pénzügyi fázis előzményére hivatkozhat.")
    reference_key = (int(reference.get("position") or 0), int(reference.get("id") or 0))
    candidate_id = int(row_id) if row_id is not None else max(
        (int(row.get("id") or 0) for row in rows.data),
        default=0,
    ) + 1
    if reference_key >= (payload.position, candidate_id):
        raise ConflictError("Egy fázis csak egy korábban szereplő fázis befejezésére hivatkozhat.")


async def _validate_milestone_set(
    project_id: int,
    candidate: dict[str, Any],
    token: str,
    gateway: SupabaseGateway,
    milestone_id: int | None = None,
    allow_missing_schedule_row: bool = False,
) -> None:
    try:
        calculated_schedule = await _calculated_schedule(project_id, token, gateway)
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    schedule_row_id = candidate.get("schedule_row_id")
    if schedule_row_id is not None:
        linked_row = next(
            (
                row
                for row in calculated_schedule
                if int(row.get("id") or 0) == int(schedule_row_id)
            ),
            None,
        )
        if linked_row is None:
            if allow_missing_schedule_row:
                candidate["schedule_row_id"] = None
            else:
                raise ConflictError("A hivatkozott ütemtervsor nem ehhez a projekthez tartozik vagy már nem létezik.")
        else:
            candidate["reference_name"] = str(linked_row.get("phase_name") or "").strip()
    normalized_candidate = normalize_milestone(candidate)
    candidate_name = normalized_candidate["official_name"]
    current = await gateway.select("project_milestones", token, filters={"project_id": f"eq.{project_id}"})
    same_name = next(
        (
            item
            for item in current.data
            if int(item["id"]) != int(milestone_id or 0)
            and normalize_milestone(item)["official_name"].casefold() == candidate_name.casefold()
        ),
        None,
    )
    if same_name:
        raise ConflictError("Ezzel a névvel már létezik szerződéses mérföldkő.")
    candidate_data = normalized_candidate
    candidate_data["id"] = milestone_id or -1
    previous = next((item for item in current.data if int(item["id"]) == int(milestone_id or 0)), None)
    old_name = normalize_milestone(previous or {}).get("official_name") or ""
    milestones = []
    for item in current.data:
        if int(item["id"]) == int(milestone_id or 0):
            continue
        copy = normalize_milestone(item)
        if (
            old_name
            and old_name != candidate_name
            and str(copy.get("date_type") or "") == MILESTONE_LINKED_DATE
            and str(copy.get("reference_name") or "").strip() == old_name
        ):
            copy["reference_name"] = candidate_name
        milestones.append(copy)
    milestones.append(candidate_data)
    try:
        calculate_milestone_dates(milestones, calculated_schedule)
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc


@router.get("/{project_id}/settings")
async def get_settings(
    project_id: int,
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> dict[str, Any]:
    templates = await gateway.select("phase_templates", token, order="name.asc,id.asc")
    try:
        schedule_keys = await gateway.select(
            "schedule_keys", token, filters={"is_active": "eq.true"}, order="code.asc,id.asc"
        )
        active_schedule_keys = schedule_keys.data
        schedule_keys_available = True
        schedule_keys_error = None
    except NotFoundError as exc:
        active_schedule_keys = []
        schedule_keys_available = False
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        schedule_keys_error = {
            "code": str(detail.get("code") or "HTTP 404"),
            "message": (
                "A futó backend Supabase REST kapcsolata nem látja a schedule_keys táblát. "
                "Ellenőrizni kell, hogy a helyi alkalmazás és az SQL Editor ugyanahhoz "
                "a Supabase projekthez kapcsolódik-e."
            ),
        }
    return {
        "project_start": (await _project_start(project_id, token, gateway)).isoformat(),
        "phase_templates": templates.data,
        "schedule_keys": active_schedule_keys,
        "schedule_keys_available": schedule_keys_available,
        "schedule_keys_error": schedule_keys_error,
    }


@router.put("/{project_id}/settings")
async def update_settings(
    project_id: int,
    payload: ScheduleSettingsWrite,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("schedule_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict[str, Any]:
    result = await gateway.upsert(
        "schedule_entries",
        token,
        {"project_id": project_id, "phase": PROJECT_START_PHASE, "entry_date": payload.project_start.isoformat()},
        on_conflict="project_id,phase",
    )
    await _refresh_dynamic_milestones(project_id, token, gateway)
    return result[0] if result else {"project_id": project_id, "phase": PROJECT_START_PHASE, "entry_date": payload.project_start.isoformat()}


@router.get("/{project_id}/timeline")
async def get_timeline(
    project_id: int,
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
    financial_phase_no: int | None = Query(default=None, ge=0, le=5),
) -> dict[str, Any]:
    return await _timeline(project_id, token, gateway, financial_phase_no=financial_phase_no)


@router.get("/{project_id}/export.xlsx")
async def export_schedule(
    project_id: int,
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
    financial_phase_no: int | None = Query(default=None, ge=0, le=5),
) -> StreamingResponse:
    project = await gateway.select("projects", token, filters={"id": f"eq.{project_id}"}, limit=1)
    if not project.data:
        raise NotFoundError("A projekt nem található.")
    timeline = await _timeline(project_id, token, gateway, financial_phase_no=financial_phase_no)
    try:
        output = build_schedule_workbook(
            str(project.data[0].get("name") or f"Projekt {project_id}"),
            date.fromisoformat(timeline["project_start"]),
            timeline["rows"],
            timeline["milestones"],
        )
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="utemterv-{project_id}'
                f'{"-penzugyi-fazis-" + str(financial_phase_no) if financial_phase_no is not None else ""}.xlsx"'
            )
        },
    )


@router.get("/{project_id}/rows")
async def list_rows(
    project_id: int,
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
    financial_phase_no: int | None = Query(default=None, ge=0, le=5),
) -> list[dict]:
    filters = {"project_id": f"eq.{project_id}"}
    if financial_phase_no is not None:
        filters["financial_phase_no"] = f"eq.{financial_phase_no}"
    result = await gateway.select("schedule_rows", token, filters=filters, order="position.asc,id.asc")
    return result.data


@router.post("/{project_id}/calculate")
async def calculate(
    project_id: int,
    payload: ScheduleCalculationRequest,
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> list[dict]:
    return (await _timeline(project_id, token, gateway, payload.project_start))["rows"]


@router.put("/{project_id}/rows/reorder")
async def reorder_rows(
    project_id: int,
    payload: ScheduleReorderRequest,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("schedule_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> list[dict]:
    result = await gateway.select("schedule_rows", token, filters={"project_id": f"eq.{project_id}"})
    by_id = {int(item["id"]): item for item in result.data}
    if len(payload.row_ids) != len(by_id) or set(payload.row_ids) != set(by_id):
        raise ConflictError("Az új sorrendnek a projekt minden ütemtervi sorát pontosan egyszer kell tartalmaznia.")
    positions = {row_id: (index + 1) * 10 for index, row_id in enumerate(payload.row_ids)}
    names = {str(item.get("phase_name") or ""): row_id for row_id, item in by_id.items()}
    for row_id in payload.row_ids:
        reference = str(by_id[row_id].get("reference_name") or PROJECT_START_LABEL)
        if reference != PROJECT_START_LABEL:
            reference_id = names.get(reference)
            if reference_id is None or positions[reference_id] >= positions[row_id]:
                raise ConflictError("A sorrend nem módosítható úgy, hogy egy fázis a saját előzménye elé kerüljön.")
    for row_id, position in positions.items():
        await gateway.update(
            "schedule_rows", token, {"position": position}, {"id": f"eq.{row_id}", "project_id": f"eq.{project_id}"}
        )
    await _refresh_dynamic_milestones(project_id, token, gateway)
    return (await gateway.select(
        "schedule_rows", token, filters={"project_id": f"eq.{project_id}"}, order="position.asc,id.asc"
    )).data


@router.post("/{project_id}/rows")
async def create_row(
    project_id: int,
    payload: ScheduleRowCreate,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("schedule_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    await _validate_schedule_row(project_id, payload, token, gateway)
    data = payload.model_dump(mode="json")
    data["project_id"] = project_id
    result = await gateway.insert("schedule_rows", token, data)
    await _refresh_dynamic_milestones(project_id, token, gateway)
    return result[0]


@router.put("/{project_id}/rows/{row_id}")
async def update_row(
    project_id: int,
    row_id: int,
    payload: ScheduleRowCreate,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("schedule_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    previous = await gateway.select(
        "schedule_rows", token, filters={"id": f"eq.{row_id}", "project_id": f"eq.{project_id}"}, limit=1
    )
    if not previous.data:
        raise NotFoundError("Az ütemtervsor nem található.")
    await _validate_schedule_row(project_id, payload, token, gateway, row_id)
    data = payload.model_dump(mode="json")
    for optional_field in ("section", "phase_code", "schedule_key_id", "financial_phase_no"):
        if optional_field not in payload.model_fields_set:
            data.pop(optional_field, None)
    if "schedule_key_id" in payload.model_fields_set and payload.schedule_key_id is None:
        data["phase_code"] = None
    data["project_id"] = project_id
    result = await gateway.update(
        "schedule_rows", token, data, {"id": f"eq.{row_id}", "project_id": f"eq.{project_id}"}
    )
    if not result:
        raise NotFoundError("Az ütemtervsor nem található.")
    old_name = str(previous.data[0].get("phase_name") or "").strip()
    new_name = payload.phase_name.strip()
    if old_name and old_name != new_name:
        await gateway.update(
            "schedule_rows",
            token,
            {"reference_name": new_name},
            {"project_id": f"eq.{project_id}", "reference_name": f"eq.{old_name}"},
        )
        await gateway.update(
            "project_milestones",
            token,
            {"reference_name": new_name},
            {
                "project_id": f"eq.{project_id}",
                "date_type": f"eq.{SCHEDULE_LINKED_DATE}",
                "reference_name": f"eq.{old_name}",
            },
        )
    await _refresh_dynamic_milestones(project_id, token, gateway)
    return result[0]


@router.delete("/{project_id}/rows")
async def clear_rows(
    project_id: int,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("schedule_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict[str, bool]:
    linked = await gateway.select(
        "project_milestones",
        token,
        filters={"project_id": f"eq.{project_id}", "date_type": f"eq.{SCHEDULE_LINKED_DATE}"},
        limit=1,
    )
    if linked.data:
        raise ConflictError("Az ütemterv nem üríthető, mert legalább egy szerződéses mérföldkő fázishoz kötött.")
    await gateway.delete("schedule_rows", token, {"project_id": f"eq.{project_id}"})
    return {"deleted": True}


@router.delete("/{project_id}/rows/{row_id}")
async def delete_row(
    project_id: int,
    row_id: int,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("schedule_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict[str, bool]:
    row = await gateway.select(
        "schedule_rows", token, filters={"id": f"eq.{row_id}", "project_id": f"eq.{project_id}"}, limit=1
    )
    if not row.data:
        raise NotFoundError("Az ütemtervsor nem található.")
    phase_name = row.data[0]["phase_name"]
    dependants = await gateway.select(
        "schedule_rows",
        token,
        filters={"project_id": f"eq.{project_id}", "reference_name": f"eq.{phase_name}"},
        limit=1,
    )
    milestone_dependants = await gateway.select(
        "project_milestones",
        token,
        filters={
            "project_id": f"eq.{project_id}",
            "date_type": f"eq.{SCHEDULE_LINKED_DATE}",
            "reference_name": f"eq.{phase_name}",
            "schedule_row_id": "is.null",
        },
        limit=1,
    )
    if dependants.data or milestone_dependants.data:
        raise ConflictError("A fázis nem törölhető, mert más fázis vagy szerződéses mérföldkő hivatkozik rá.")
    await gateway.delete("schedule_rows", token, {"id": f"eq.{row_id}", "project_id": f"eq.{project_id}"})
    return {"deleted": True}


@router.get("/{project_id}/contract-sections")
async def list_contract_sections(
    project_id: int,
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> list[dict]:
    result = await gateway.select(
        "project_contract_sections",
        token,
        filters={"project_id": f"eq.{project_id}"},
        order="section_no.asc,id.asc",
    )
    return result.data


@router.post("/{project_id}/contract-sections")
async def create_contract_section(
    project_id: int,
    payload: ContractSectionWrite,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("schedule_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    existing = await gateway.select(
        "project_contract_sections",
        token,
        filters={"project_id": f"eq.{project_id}", "section_no": f"eq.{payload.section_no}"},
        limit=1,
    )
    if existing.data:
        raise ConflictError("Ez a főszerződéses szakasz már létezik.")
    data = payload.model_dump(mode="json")
    data["project_id"] = project_id
    result = await gateway.insert("project_contract_sections", token, data)
    await _sync_project_contract_value(project_id, token, gateway)
    return result[0]


@router.put("/{project_id}/contract-sections/{section_id}")
async def update_contract_section(
    project_id: int,
    section_id: int,
    payload: ContractSectionWrite,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("schedule_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    previous = await gateway.select(
        "project_contract_sections",
        token,
        filters={"id": f"eq.{section_id}", "project_id": f"eq.{project_id}"},
        limit=1,
    )
    if not previous.data:
        raise NotFoundError("A főszerződéses szakasz nem található.")
    duplicate = await gateway.select(
        "project_contract_sections",
        token,
        filters={"project_id": f"eq.{project_id}", "section_no": f"eq.{payload.section_no}", "id": f"neq.{section_id}"},
        limit=1,
    )
    if duplicate.data:
        raise ConflictError("Ez a főszerződéses szakasz már létezik.")
    data = payload.model_dump(mode="json")
    data["project_id"] = project_id
    result = await gateway.update(
        "project_contract_sections", token, data, {"id": f"eq.{section_id}", "project_id": f"eq.{project_id}"}
    )
    await _sync_project_contract_value(project_id, token, gateway)
    affected_phases = {int(previous.data[0]["section_no"]), payload.section_no}
    for phase_no in affected_phases:
        for milestone in await _phase_milestones(project_id, phase_no, token, gateway):
            await _reopen_revenue_payment(project_id, int(milestone["id"]), token, gateway)
    return result[0]


@router.delete("/{project_id}/contract-sections/{section_id}")
async def delete_contract_section(
    project_id: int,
    section_id: int,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("schedule_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict[str, bool]:
    section = await gateway.select(
        "project_contract_sections",
        token,
        filters={"id": f"eq.{section_id}", "project_id": f"eq.{project_id}"},
        limit=1,
    )
    if not section.data:
        raise NotFoundError("A főszerződéses szakasz nem található.")
    phase_no = int(section.data[0]["section_no"])
    milestones = await _phase_milestones(project_id, phase_no, token, gateway)
    if milestones:
        raise ConflictError("A szakasz nem törölhető, amíg szerződéses mérföldkő tartozik hozzá.")
    schedule_rows = await gateway.select(
        "schedule_rows",
        token,
        filters={"project_id": f"eq.{project_id}", "financial_phase_no": f"eq.{phase_no}"},
        limit=1,
    )
    if schedule_rows.data:
        raise ConflictError("A pénzügyi fázis nem törölhető, amíg ütemtervi jelkulcs tartozik hozzá.")
    await gateway.delete(
        "project_contract_sections", token, {"id": f"eq.{section_id}", "project_id": f"eq.{project_id}"}
    )
    await _sync_project_contract_value(project_id, token, gateway)
    return {"deleted": True}


@router.get("/{project_id}/milestones")
async def list_milestones(
    project_id: int,
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> list[dict]:
    result = await gateway.select(
        "project_milestones",
        token,
        filters={"project_id": f"eq.{project_id}"},
        order="phase_no.asc,sequence_no.asc,id.asc",
    )
    schedule_rows = await gateway.select(
        "schedule_rows",
        token,
        filters={"project_id": f"eq.{project_id}"},
    )
    return [normalize_milestone(item, schedule_rows.data) for item in result.data]


@router.post("/{project_id}/milestones")
async def create_milestone(
    project_id: int,
    payload: ProjectMilestoneWrite,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("schedule_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    data = _milestone_write_data(payload)
    await _validate_milestone_set(project_id, data, token, gateway)
    data["project_id"] = project_id
    result = await gateway.insert("project_milestones", token, data)
    refreshed = await _refresh_dynamic_milestones(project_id, token, gateway)
    return next((item for item in refreshed if int(item["id"]) == int(result[0]["id"])), result[0])


@router.put("/{project_id}/milestones/{milestone_id}")
async def update_milestone(
    project_id: int,
    milestone_id: int,
    payload: ProjectMilestoneWrite,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("schedule_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    previous = await gateway.select(
        "project_milestones",
        token,
        filters={"id": f"eq.{milestone_id}", "project_id": f"eq.{project_id}"},
        limit=1,
    )
    if not previous.data:
        raise NotFoundError("A mérföldkő nem található.")
    data = _milestone_write_data(payload, previous.data[0])
    await _validate_milestone_set(
        project_id,
        data,
        token,
        gateway,
        milestone_id,
        allow_missing_schedule_row="schedule_row_id" not in payload.model_fields_set,
    )
    data["project_id"] = project_id
    result = await gateway.update(
        "project_milestones",
        token,
        data,
        {"id": f"eq.{milestone_id}", "project_id": f"eq.{project_id}"},
    )
    old_name = normalize_milestone(previous.data[0])["official_name"]
    new_name = data["official_name"]
    if old_name and old_name != new_name:
        await gateway.update(
            "project_milestones",
            token,
            {"reference_name": new_name},
            {
                "project_id": f"eq.{project_id}",
                "date_type": f"eq.{MILESTONE_LINKED_DATE}",
                "reference_name": f"eq.{old_name}",
            },
        )
    refreshed = await _refresh_dynamic_milestones(project_id, token, gateway)
    await _reopen_revenue_payment(project_id, milestone_id, token, gateway)
    return next((item for item in refreshed if int(item["id"]) == milestone_id), normalize_milestone(result[0]))


@router.delete("/{project_id}/milestones/{milestone_id}")
async def delete_milestone(
    project_id: int,
    milestone_id: int,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("schedule_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict[str, bool]:
    milestone = await gateway.select(
        "project_milestones",
        token,
        filters={"id": f"eq.{milestone_id}", "project_id": f"eq.{project_id}"},
        limit=1,
    )
    if not milestone.data:
        raise NotFoundError("A mérföldkő nem található.")
    milestone_name = normalize_milestone(milestone.data[0])["official_name"]
    dependants = await gateway.select(
        "project_milestones",
        token,
        filters={
            "project_id": f"eq.{project_id}",
            "date_type": f"eq.{MILESTONE_LINKED_DATE}",
            "reference_name": f"eq.{milestone_name}",
        },
        limit=1,
    )
    if dependants.data:
        raise ConflictError("A mérföldkő nem törölhető, mert egy másik mérföldkő hivatkozik rá.")
    revenue_payment = await gateway.select(
        "payments",
        token,
        filters={"project_id": f"eq.{project_id}", "reference": f"eq.BEV_MS_{milestone_id}"},
        limit=1,
    )
    project_payments = await gateway.select("payments", token, filters={"project_id": f"eq.{project_id}"})
    cost_reference_suffix = f"_COL_M_{milestone_id}"
    has_cost_payment = any(
        str(payment.get("reference") or "").upper().endswith(cost_reference_suffix)
        for payment in project_payments.data
    )
    if revenue_payment.data or has_cost_payment:
        raise ConflictError("A mérföldkő nem törölhető, mert már pénzügyi folyamat hivatkozik rá.")
    await gateway.delete(
        "contract_matrix", token, {"project_id": f"eq.{project_id}", "column_code": f"eq.M_{milestone_id}"}
    )
    await gateway.delete(
        "project_milestones", token, {"id": f"eq.{milestone_id}", "project_id": f"eq.{project_id}"}
    )
    return {"deleted": True}
