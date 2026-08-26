from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import logging
import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import Response, StreamingResponse

from ..hitelesites import AccessToken, AuthenticatedUser, CsrfProtected, get_gateway
from ..hibak import ConflictError, NotFoundError, UpstreamError
from ..adatmodellek.alvallalkozok import (
    ContractBaseValue,
    ContractChangeCreate,
    ContractMatrixCell,
    ContractPart,
    ContractStageCreate,
    FolderCreate,
    FolderReorderRequest,
    OfferPart,
    SubcontractorCreate,
    WorkflowCreate,
    WorkflowScheduleKeyAssignments,
    WorkflowStepRequest,
    WorkflowUpdate,
)
from ..adatmodellek.dokumentumok import OfferRequestDocumentWrite
from ..jogosultsagok import ensure_project_access, require_permission
from ..szolgaltatasok.penzugy import parse_money
from ..szolgaltatasok.alvallalkozok import (
    build_subcontractor_workbook,
    matrix_payment_reference,
    normalize_workflow_money,
    validate_step_close,
)
from ..szolgaltatasok.dokumentumok import build_offer_request_pdf, build_offer_request_word
from ..supabase_kapcsolat import SupabaseGateway


router = APIRouter(prefix="/subcontractors", tags=["subcontractors"])
logger = logging.getLogger("project_control.finance_math")


async def _optional_table_rows(
    gateway: SupabaseGateway,
    table: str,
    token: str,
    **select_options: Any,
) -> list[dict[str, Any]]:
    """Keep document generation usable while an optional settings migration is pending."""
    try:
        result = await gateway.select(table, token, **select_options)
    except NotFoundError:
        logger.warning("Optional document table is unavailable table=%s", table)
        return []
    return result.data


async def _optional_table_rows_with_availability(
    gateway: SupabaseGateway,
    table: str,
    token: str,
    **select_options: Any,
) -> tuple[list[dict[str, Any]], bool]:
    try:
        result = await gateway.select(table, token, **select_options)
    except NotFoundError:
        logger.warning("Optional table is unavailable table=%s", table)
        return [], False
    return result.data, True


def _as_iso_date(value: object) -> str:
    return str(value or "")[:10]


def _strict_matrix_columns(
    milestones: list[dict[str, Any]],
    stages: list[dict[str, Any]],
    cells: list[dict[str, Any]],
    fallback_date: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return one dated, stable column sequence for both header rows."""
    warnings: list[str] = []
    columns: list[dict[str, Any]] = []
    known_codes: set[str] = set()

    for milestone in milestones:
        code = f"M_{milestone['id']}"
        effective_date = _as_iso_date(
            milestone.get("actual_date") or milestone.get("planned_date")
        )
        used_fallback = not bool(effective_date)
        if used_fallback:
            effective_date = fallback_date
            warnings.append(
                f"A(z) {milestone.get('name') or code} mérföldkő dátuma hiányzott; "
                f"a mátrix ideiglenesen a projekt alapdátumát használja."
            )
        columns.append(
            {
                "id": None,
                "milestone_id": milestone["id"],
                "name": milestone.get("name") or code,
                "stage_date": effective_date,
                "effective_date": effective_date,
                "phase_no": int(milestone.get("phase_no") or 1),
                "fee_percent": milestone.get("fee_percent") or 0,
                "copyright_percent": milestone.get("copyright_percent") or 0,
                "code": code,
                "source": "milestone",
                "used_fallback_date": used_fallback,
            }
        )
        known_codes.add(code)

    for stage in stages:
        code = f"STAGE_{stage['id']}"
        effective_date = _as_iso_date(stage.get("stage_date"))
        used_fallback = not bool(effective_date)
        if used_fallback:
            effective_date = fallback_date
            warnings.append(
                f"A(z) {stage.get('name') or code} oszlop dátuma hiányzott; "
                f"futtasd a 008_matrix_datumok.sql migrációt."
            )
        columns.append(
            {
                "id": stage["id"],
                "name": stage.get("name") or code,
                "stage_date": effective_date,
                "effective_date": effective_date,
                "phase_no": None,
                "fee_percent": 0,
                "copyright_percent": 0,
                "code": code,
                "source": "stage",
                "used_fallback_date": used_fallback,
            }
        )
        known_codes.add(code)

    legacy_codes = sorted(
        {
            str(cell.get("column_code") or "").strip()
            for cell in cells
            if str(cell.get("column_code") or "").strip()
            and str(cell.get("column_code") or "").strip().upper() != "BASE"
            and str(cell.get("column_code") or "").strip() not in known_codes
        },
        key=str.casefold,
    )
    for code in legacy_codes:
        columns.append(
            {
                "id": None,
                "name": "Hóközi / előleg" if code.upper().startswith("EMP_") else code,
                "stage_date": fallback_date,
                "effective_date": fallback_date,
                "phase_no": None,
                "fee_percent": 0,
                "copyright_percent": 0,
                "code": code,
                "source": "legacy",
                "used_fallback_date": True,
            }
        )
        warnings.append(
            f"A(z) {code} régi mátrixoszlop még nincs dátumozott szakaszhoz kötve; "
            f"futtasd a 008_matrix_datumok.sql migrációt."
        )

    source_order = {"milestone": 0, "stage": 1, "legacy": 2}
    columns.sort(
        key=lambda item: (
            str(item["effective_date"]),
            source_order.get(str(item["source"]), 9),
            int(item.get("phase_no") or 0),
            str(item["code"]).casefold(),
        )
    )
    return columns, warnings


def _offer_request_schedule(milestones: list[dict[str, Any]]) -> str:
    lines = []
    for milestone in milestones:
        name = str(milestone.get("name") or "").strip()
        planned_date = _as_iso_date(milestone.get("planned_date"))
        if name and planned_date:
            lines.append(f"{planned_date}: {name}")
    return "\n".join(lines)


def _offer_request_finance(sections: list[dict[str, Any]]) -> str:
    lines = []
    for section in sections:
        number = section.get("section_no")
        original = section.get("original_fee")
        modified = section.get("modified_fee")
        value = modified if modified not in (None, "", 0, "0") else original
        if number is not None and value not in (None, ""):
            lines.append(f"{number}. szerzodeses szakasz: {value} Ft")
    return "\n".join(lines)


async def _workflow_for_document(
    project_id: int,
    workflow_id: int,
    token: str,
    gateway: SupabaseGateway,
) -> dict[str, Any]:
    result = await gateway.select(
        "subcontractor_workflows",
        token,
        filters={
            "id": f"eq.{workflow_id}",
            "project_id": f"eq.{project_id}",
            "is_deleted": "eq.false",
        },
        limit=1,
    )
    if not result.data:
        raise NotFoundError("Az alvállalkozói folyamat nem található.")
    return result.data[0]


async def _offer_request_defaults(
    project_id: int,
    workflow: dict[str, Any],
    token: str,
    gateway: SupabaseGateway,
) -> dict[str, Any]:
    project, milestones, sections, document_settings = await asyncio.gather(
        gateway.select("projects", token, filters={"id": f"eq.{project_id}", "is_deleted": "eq.false"}, limit=1),
        gateway.select("project_milestones", token, filters={"project_id": f"eq.{project_id}"}, order="planned_date.asc,sequence_no.asc,id.asc"),
        gateway.select("project_contract_sections", token, filters={"project_id": f"eq.{project_id}"}, order="section_no.asc,id.asc"),
        _optional_table_rows(
            gateway,
            "project_offer_request_settings",
            token,
            filters={"project_id": f"eq.{project_id}"},
            limit=1,
        ),
    )
    if not project.data:
        raise NotFoundError("A projekt nem található.")
    project_row = project.data[0]
    settings_row = document_settings[0] if document_settings else {}
    return {
        "title": "Árajánlatkérő",
        "project_name": str(project_row.get("name") or ""),
        "company_name": str(workflow.get("company_name") or ""),
        "discipline": str(workflow.get("discipline") or ""),
        "work_number": str(project_row.get("work_number") or ""),
        "history": str(settings_row.get("history") or ""),
        "task_description": str(settings_row.get("task_description") or workflow.get("status_note") or ""),
        "request_text": "Kérjük árajánlatukat megadni szíveskedjenek a fenti feladat elvégzésére.",
        "response_deadline": "",
        "schedule_text": _offer_request_schedule(milestones.data),
        "finance_text": _offer_request_finance(sections.data),
        "note": "",
        "attachments": "",
        "contacts": "",
        "document_date": date.today().isoformat(),
    }


async def _offer_request_snapshot(
    project_id: int,
    workflow: dict[str, Any],
    payload: OfferRequestDocumentWrite,
    token: str,
    gateway: SupabaseGateway,
) -> dict[str, Any]:
    defaults = await _offer_request_defaults(project_id, workflow, token, gateway)
    manual = payload.data.model_dump(mode="json")
    return {**defaults, **manual, "title": payload.title or defaults["title"]}


async def _offer_request_document_for_export(
    project_id: int,
    workflow_id: int,
    document_id: int,
    token: str,
    gateway: SupabaseGateway,
) -> dict[str, Any]:
    """Load one saved document only after explicit project access and RLS checks."""
    await ensure_project_access(gateway, token, project_id)
    await _workflow_for_document(project_id, workflow_id, token, gateway)
    documents = await gateway.select(
        "workflow_documents",
        token,
        filters={
            "id": f"eq.{document_id}",
            "project_id": f"eq.{project_id}",
            "workflow_id": f"eq.{workflow_id}",
            "document_type": "eq.offer_request",
        },
        limit=1,
    )
    if not documents.data:
        raise NotFoundError("A dokumentum nem található.")
    document = dict(documents.data[0])
    snapshot = document.get("data")
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except json.JSONDecodeError as exc:
            raise ConflictError("A mentett dokumentum tartalma sérült, ezért nem exportálható.") from exc
    if not isinstance(snapshot, dict):
        raise ConflictError("A mentett dokumentum tartalma sérült, ezért nem exportálható.")
    document["data"] = snapshot
    return document


async def _saved_offer_request_document(
    project_id: int,
    workflow_id: int,
    document_id: int,
    token: str,
    gateway: SupabaseGateway,
) -> dict[str, Any]:
    result = await gateway.select(
        "workflow_documents",
        token,
        filters={
            "id": f"eq.{document_id}",
            "project_id": f"eq.{project_id}",
            "workflow_id": f"eq.{workflow_id}",
            "document_type": "eq.offer_request",
        },
        limit=1,
    )
    if not result.data:
        raise UpstreamError("A dokumentum mentése nem adott vissza betölthető rekordot.")
    return result.data[0]


def _offer_request_file_response(
    document: dict[str, Any],
    workflow_id: int,
    export_format: Literal["pdf", "word"],
    *,
    inline: bool,
) -> Response:
    revision = int(document.get("revision_no") or 1)
    snapshot = document.get("data") or {}
    if export_format == "word":
        content = build_offer_request_word(snapshot)
        extension = "docx"
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        content = build_offer_request_pdf(snapshot)
        extension = "pdf"
        media_type = "application/pdf"
    disposition = "inline" if inline else "attachment"
    filename = f"ajanlatkero-{workflow_id}-v{revision}.{extension}"
    return Response(
        content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


def _folder_position(value: int, item_count: int) -> int:
    if value <= 0:
        return item_count
    return min(value - 1, item_count)


async def _persist_folder_order(
    project_id: int,
    folders: list[dict],
    token: str,
    gateway: SupabaseGateway,
) -> list[dict]:
    payload = [
        {
            "id": int(folder["id"]),
            "project_id": project_id,
            "name": str(folder.get("name") or ""),
            "code": str(folder.get("code") or ""),
            "display_order": index * 10,
        }
        for index, folder in enumerate(folders, 1)
    ]
    if not payload:
        return []
    return await gateway.upsert(
        "subcontractor_folders",
        token,
        payload,
        on_conflict="id",
    )


async def _sync_single_part_bases(
    project_id: int,
    workflow: dict,
    token: str,
    gateway: SupabaseGateway,
    *,
    allow_reopen: bool = False,
    apply: bool = True,
) -> list[dict]:
    if int(workflow.get("part_count") or 1) != 1 or workflow.get("acceptance") != "Elfogadva" or int(workflow.get("current_step") or 1) < 5:
        return []
    workflow_id = int(workflow["id"])
    fee = parse_money(workflow.get("modified_fee")) or parse_money(workflow.get("contract_fee"))
    copyright_fee = parse_money(workflow.get("modified_copyright_fee")) or parse_money(workflow.get("copyright_fee"))
    bases = [
        {"project_id": project_id, "reference_id": f"ALV_{workflow_id}_SZ1_MD", "amount": float(fee)},
        {"project_id": project_id, "reference_id": f"ALV_{workflow_id}_SZ1_SZJD", "amount": float(copyright_fee)},
    ]
    logger.info(
        "finance_math base_sync project_id=%s workflow_id=%s fee=%s copyright_fee=%s",
        project_id,
        workflow_id,
        fee,
        copyright_fee,
    )
    changed_references: set[str] = set()
    changed_cells: list[tuple[dict, Decimal]] = []
    for base in bases:
        cells = await gateway.select("contract_matrix", token, filters={"project_id": f"eq.{project_id}", "reference_id": f"eq.{base['reference_id']}"})
        for cell in cells.data:
            if cell.get("percent") is None:
                continue
            amount = (Decimal(str(base["amount"])) * Decimal(str(cell.get("percent") or 0)) / Decimal("100")).quantize(Decimal("0.01"))
            logger.info(
                "finance_math base_recalc project_id=%s workflow_id=%s reference=%s "
                "base=%s percent=%s old_amount=%s result_amount=%s rounding=0.01",
                project_id,
                workflow_id,
                base["reference_id"],
                base["amount"],
                cell.get("percent") or 0,
                cell.get("amount") or 0,
                amount,
            )
            if abs(amount - Decimal(str(cell.get("amount") or 0))) < Decimal("0.01"):
                continue
            changed_cells.append((cell, amount))
            reference = matrix_payment_reference(base["reference_id"], str(cell.get("column_code") or ""))
            if reference:
                changed_references.add(reference)
    completed = await gateway.select("payments", token, filters={"project_id": f"eq.{project_id}", "status": "eq.Pénzügyileg teljesítve"}) if changed_references else None
    impacted = [payment for payment in (completed.data if completed else []) if str(payment.get("reference") or "").upper() in changed_references]
    if impacted and not allow_reopen:
        raise ConflictError(
            "A szerződéses összeg módosítása pénzügyileg teljesített tételeket érint. A mentéshez jóvá kell hagyni a pénzügyi státuszok visszanyitását.",
            detail={"requires_reopen": True, "payment_ids": [payment.get("id") for payment in impacted]},
        )
    if not apply:
        return [{"payment_id": payment.get("id"), "reference": payment.get("reference"), "old_amount": payment.get("amount", 0)} for payment in impacted]
    await gateway.upsert("contract_base_values", token, bases, on_conflict="project_id,reference_id")
    for cell, amount in changed_cells:
        await gateway.update("contract_matrix", token, {"amount": float(amount)}, {"id": f"eq.{cell['id']}", "project_id": f"eq.{project_id}"})
    reopened: list[dict] = []
    for payment in impacted:
        await gateway.update("payments", token, {"status": "Várható", "payment_date": None}, {"id": f"eq.{payment['id']}", "project_id": f"eq.{project_id}"})
        reopened.append({"payment_id": payment.get("id"), "reference": payment.get("reference"), "old_amount": payment.get("amount", 0)})
    return reopened


async def _completed_payment_impact(
    project_id: int,
    cell: ContractMatrixCell,
    token: str,
    gateway: SupabaseGateway,
    *,
    old_amount: Decimal = Decimal("0"),
) -> tuple[dict | None, Decimal]:
    workflow_match = re.match(r"ALV_(\d+)_", cell.reference_id, re.IGNORECASE)
    column_code = str(cell.column_code or "").strip().upper()
    if not workflow_match or not re.fullmatch(r"(?:M|STAGE)_\d+|EMP_.+", column_code):
        return None, Decimal("0")
    workflow_id = int(workflow_match.group(1))
    reference = matrix_payment_reference(cell.reference_id, column_code)
    if not reference:
        return None, Decimal("0")
    allocations = await gateway.select(
        "contract_matrix",
        token,
        filters={"project_id": f"eq.{project_id}", "column_code": f"eq.{cell.column_code}"},
    )
    workflow_prefix = f"ALV_{workflow_id}_"
    expected = sum(
        (
            Decimal(str(item.get("amount") or 0))
            for item in allocations.data
            if str(item.get("reference_id") or "").upper().startswith(workflow_prefix)
        ),
        Decimal("0"),
    )
    expected = expected - old_amount + Decimal(str(cell.amount or 0))
    payments = await gateway.select("payments", token, filters={"project_id": f"eq.{project_id}", "reference": f"eq.{reference}"}, limit=1)
    if not payments.data:
        return None, expected
    payment = payments.data[0]
    actual = Decimal(str(payment.get("amount") or 0))
    impacted = payment if payment.get("status") == "Pénzügyileg teljesítve" and abs(actual - expected) >= Decimal("0.01") else None
    return impacted, expected


async def _normalize_matrix_cell(project_id: int, cell: ContractMatrixCell, token: str, gateway: SupabaseGateway) -> dict:
    payload = cell.model_dump(mode="json", exclude={"calculation_source", "reopen_completed_payment"})
    payload["project_id"] = project_id
    if cell.calculation_source == "text":
        payload["percent"] = None
        payload["amount"] = 0
        return payload
    bases = await gateway.select(
        "contract_base_values",
        token,
        filters={"project_id": f"eq.{project_id}", "reference_id": f"eq.{cell.reference_id}"},
        limit=1,
    )
    base = Decimal(str(bases.data[0].get("amount") or 0)) if bases.data else Decimal("0")
    if not base:
        payload["percent"] = None if cell.percent is None else float(cell.percent)
        payload["amount"] = float(Decimal(str(cell.amount or 0)).quantize(Decimal("0.01")))
    elif cell.calculation_source == "percent":
        percent = Decimal(str(cell.percent or 0))
        payload["percent"] = float(percent)
        payload["amount"] = float((base * percent / Decimal("100")).quantize(Decimal("0.01")))
    else:
        amount = Decimal(str(cell.amount or 0)).quantize(Decimal("0.01"))
        payload["amount"] = float(amount)
        payload["percent"] = float((amount / base * Decimal("100")).quantize(Decimal("0.0001")))
    logger.info(
        "finance_math matrix_cell project_id=%s reference=%s column=%s source=%s "
        "base=%s input_percent=%s input_amount=%s result_percent=%s "
        "result_amount=%s amount_rounding=0.01 percent_rounding=0.0001",
        project_id,
        cell.reference_id,
        cell.column_code,
        cell.calculation_source,
        base,
        cell.percent,
        cell.amount,
        payload.get("percent"),
        payload.get("amount"),
    )
    return payload


async def _save_matrix_cell(
    project_id: int,
    cell: ContractMatrixCell,
    token: str,
    gateway: SupabaseGateway,
    *,
    cell_id: int | None = None,
) -> tuple[dict, dict | None]:
    payload = await _normalize_matrix_cell(project_id, cell, token, gateway)
    filters = {
        "project_id": f"eq.{project_id}",
        "reference_id": f"eq.{cell.reference_id}",
        "column_code": f"eq.{cell.column_code}",
        "stage_id": f"eq.{cell.stage_id}" if cell.stage_id is not None else "is.null",
    }
    existing = await gateway.select(
        "contract_matrix",
        token,
        filters={"id": f"eq.{cell_id}", "project_id": f"eq.{project_id}"} if cell_id else filters,
        limit=1,
    )
    if cell_id and not existing.data:
        raise NotFoundError("A mátrixcella nem található.")
    if existing.data:
        stored = existing.data[0]
        if cell_id and (
            str(stored.get("reference_id") or "") != cell.reference_id
            or str(stored.get("column_code") or "") != cell.column_code
            or stored.get("stage_id") != cell.stage_id
        ):
            raise ConflictError("A mátrixcella hivatkozása nem módosítható.")
        old_amount = Decimal(str(stored.get("amount") or 0))
    else:
        stored = None
        old_amount = Decimal("0")
    normalized_cell = cell.model_copy(update={"amount": float(payload["amount"]), "percent": payload.get("percent")})
    impacted, expected = await _completed_payment_impact(
        project_id,
        normalized_cell,
        token,
        gateway,
        old_amount=old_amount,
    )
    if impacted and not cell.reopen_completed_payment:
        raise ConflictError(
            "A cellához pénzügyileg teljesített tétel tartozik. A módosítás csak a pénzügyi státusz visszanyitásának jóváhagyásával menthető.",
            detail={
                "requires_reopen": True,
                "payment_id": impacted.get("id"),
                "old_amount": impacted.get("amount", 0),
                "new_amount": float(expected),
            },
        )
    if stored:
        result = await gateway.update("contract_matrix", token, payload, {"id": f"eq.{stored['id']}", "project_id": f"eq.{project_id}"})
    else:
        result = await gateway.insert("contract_matrix", token, payload)
    reopened = None
    if impacted:
        await gateway.update(
            "payments",
            token,
            {"status": "Várható", "payment_date": None},
            {"id": f"eq.{impacted['id']}", "project_id": f"eq.{project_id}"},
        )
        reopened = {
            "payment_id": impacted.get("id"),
            "reference": impacted.get("reference"),
            "old_amount": impacted.get("amount", 0),
            "new_amount": float(expected),
        }
    return result[0], reopened


@router.get("/{project_id}/workflows")
async def list_workflows(project_id: int, token: AccessToken, _: AuthenticatedUser, gateway: Annotated[SupabaseGateway, Depends(get_gateway)]) -> list[dict]:
    result = await gateway.select("subcontractor_workflows", token, filters={"project_id": f"eq.{project_id}", "is_deleted": "eq.false"}, order="display_order.asc,id.asc")
    if not result.data:
        return []
    workflow_ids = ",".join(str(int(item["id"])) for item in result.data)
    parts, key_assignments = await asyncio.gather(
        gateway.select("offer_parts", token, filters={"workflow_id": f"in.({workflow_ids})"}, order="id.asc"),
        _optional_table_rows(
            gateway,
            "subcontractor_workflow_schedule_keys",
            token,
            filters={"project_id": f"eq.{project_id}", "workflow_id": f"in.({workflow_ids})"},
            order="financial_phase_no.asc,schedule_key_id.asc,id.asc",
        ),
    )
    by_workflow: dict[int, list[dict]] = {}
    for part in parts.data:
        by_workflow.setdefault(int(part["workflow_id"]), []).append(part)
    keys_by_workflow: dict[int, list[dict[str, Any]]] = {}
    for assignment in key_assignments:
        keys_by_workflow.setdefault(int(assignment["workflow_id"]), []).append(assignment)
    return [
        {
            **item,
            "offer_parts": by_workflow.get(int(item["id"]), []),
            "schedule_key_assignments": keys_by_workflow.get(int(item["id"]), []),
        }
        for item in result.data
    ]


@router.get("/{project_id}/catalog")
async def subcontractor_catalog(project_id: int, token: AccessToken, _: AuthenticatedUser, gateway: Annotated[SupabaseGateway, Depends(get_gateway)]) -> dict[str, Any]:
    folders, subcontractors, categories, contract_sections, schedule_key_result, assignment_probe = await asyncio.gather(
        gateway.select("subcontractor_folders", token, filters={"project_id": f"eq.{project_id}"}, order="display_order.asc,id.asc"),
        gateway.select("subcontractors", token, filters={"active": "eq.true"}, order="display_order.asc,name.asc"),
        gateway.select("subcontractor_categories", token, order="display_order.asc,name.asc"),
        gateway.select("project_contract_sections", token, filters={"project_id": f"eq.{project_id}"}, order="section_no.asc,id.asc"),
        _optional_table_rows_with_availability(gateway, "schedule_keys", token, filters={"is_active": "eq.true"}, order="code.asc,id.asc"),
        _optional_table_rows_with_availability(gateway, "subcontractor_workflow_schedule_keys", token, filters={"project_id": f"eq.{project_id}"}, limit=1),
    )
    return {
        "folders": folders.data,
        "subcontractors": subcontractors.data,
        "categories": categories.data,
        "financial_phases": contract_sections.data,
        "schedule_keys": schedule_key_result[0],
        "schedule_keys_available": schedule_key_result[1],
        "schedule_key_assignments_available": assignment_probe[1],
    }


@router.post("/{project_id}/folders")
async def create_folder(project_id: int, folder: FolderCreate, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("subcontractor_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict:
    requested_position = int(folder.display_order or 0)
    result = await gateway.insert(
        "subcontractor_folders",
        token,
        dict(folder.model_dump(mode="json"), project_id=project_id, display_order=0),
    )
    current = await gateway.select(
        "subcontractor_folders",
        token,
        filters={"project_id": f"eq.{project_id}"},
        order="display_order.asc,id.asc",
    )
    created = result[0]
    ordered = [item for item in current.data if int(item["id"]) != int(created["id"])]
    ordered.insert(_folder_position(requested_position, len(ordered)), created)
    saved = await _persist_folder_order(project_id, ordered, token, gateway)
    return next(item for item in saved if int(item["id"]) == int(created["id"]))


@router.put("/{project_id}/folders/{folder_id}")
async def update_folder(project_id: int, folder_id: int, folder: FolderCreate, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("subcontractor_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict:
    current = await gateway.select(
        "subcontractor_folders",
        token,
        filters={"project_id": f"eq.{project_id}"},
        order="display_order.asc,id.asc",
    )
    existing = next((item for item in current.data if int(item["id"]) == folder_id), None)
    if not existing:
        raise NotFoundError("A szakági mappa nem található.")
    old_name = str(existing.get("name") or "")
    updated = {
        **existing,
        "name": folder.name,
        "code": folder.code,
    }
    ordered = [item for item in current.data if int(item["id"]) != folder_id]
    ordered.insert(_folder_position(int(folder.display_order or 0), len(ordered)), updated)
    saved = await _persist_folder_order(project_id, ordered, token, gateway)
    if old_name != folder.name:
        await gateway.update("subcontractor_workflows", token, {"discipline": folder.name}, {"project_id": f"eq.{project_id}", "discipline": f"eq.{old_name}", "is_deleted": "eq.false"})
    return next(item for item in saved if int(item["id"]) == folder_id)


@router.delete("/{project_id}/folders/{folder_id}")
async def delete_folder(project_id: int, folder_id: int, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("subcontractor_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict[str, bool]:
    folder = await gateway.select("subcontractor_folders", token, filters={"id": f"eq.{folder_id}", "project_id": f"eq.{project_id}"}, limit=1)
    if not folder.data:
        raise NotFoundError("A szakági mappa nem található.")
    workflows = await gateway.select("subcontractor_workflows", token, filters={"project_id": f"eq.{project_id}", "discipline": f"eq.{folder.data[0]['name']}", "is_deleted": "eq.false"}, limit=1)
    if workflows.data:
        raise ConflictError("A szakági mappa csak akkor törölhető, ha már nincs benne ajánlat vagy szerződés.")
    await gateway.delete("subcontractor_folders", token, {"id": f"eq.{folder_id}", "project_id": f"eq.{project_id}"})
    return {"deleted": True}


@router.put("/{project_id}/folder-order")
async def reorder_folders(project_id: int, payload: FolderReorderRequest, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("subcontractor_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> list[dict]:
    current = await gateway.select("subcontractor_folders", token, filters={"project_id": f"eq.{project_id}"})
    current_ids = {int(item["id"]) for item in current.data}
    if len(payload.folder_ids) != len(set(payload.folder_ids)) or set(payload.folder_ids) != current_ids:
        raise ConflictError("A szakági sorrend nem teljes vagy idegen elemet tartalmaz.")
    by_id = {int(item["id"]): item for item in current.data}
    ordered = [by_id[folder_id] for folder_id in payload.folder_ids]
    return await _persist_folder_order(project_id, ordered, token, gateway)


@router.post("/catalog/subcontractors")
async def create_subcontractor(item: SubcontractorCreate, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("subcontractor_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict:
    result = await gateway.insert("subcontractors", token, item.model_dump(mode="json"))
    return result[0]


@router.get("/{project_id}/export.xlsx")
async def export_workflows(project_id: int, token: AccessToken, user: AuthenticatedUser, gateway: Annotated[SupabaseGateway, Depends(get_gateway)]) -> StreamingResponse:
    workflows = await list_workflows(project_id, token, user, gateway)
    folders = await gateway.select("subcontractor_folders", token, filters={"project_id": f"eq.{project_id}"}, order="display_order.asc,id.asc")
    output = build_subcontractor_workbook(folders.data, workflows)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="alvallalkozok-{project_id}.xlsx"'},
    )


@router.get("/{project_id}/workflows/{workflow_id}/documents")
async def list_workflow_documents(
    project_id: int,
    workflow_id: int,
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> list[dict]:
    await _workflow_for_document(project_id, workflow_id, token, gateway)
    result = await gateway.select(
        "workflow_documents",
        token,
        filters={"project_id": f"eq.{project_id}", "workflow_id": f"eq.{workflow_id}"},
        order="document_type.asc,revision_no.desc,id.desc",
    )
    return result.data


@router.get("/{project_id}/workflows/{workflow_id}/documents/offer-request-defaults")
async def offer_request_defaults(
    project_id: int,
    workflow_id: int,
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> dict:
    workflow = await _workflow_for_document(project_id, workflow_id, token, gateway)
    defaults, contacts = await asyncio.gather(
        _offer_request_defaults(project_id, workflow, token, gateway),
        _optional_table_rows(
            gateway,
            "project_company_contacts",
            token,
            filters={"project_id": f"eq.{project_id}"},
            order="display_order.asc,name.asc,id.asc",
        ),
    )
    return {
        "title": "Árajánlatkérő",
        "data": defaults,
        "company_contacts": contacts,
    }


@router.post("/{project_id}/workflows/{workflow_id}/documents/offer-request")
async def create_offer_request_document(
    project_id: int,
    workflow_id: int,
    payload: OfferRequestDocumentWrite,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("subcontractor_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    workflow = await _workflow_for_document(project_id, workflow_id, token, gateway)
    documents = await gateway.select(
        "workflow_documents",
        token,
        filters={"project_id": f"eq.{project_id}", "workflow_id": f"eq.{workflow_id}", "document_type": "eq.offer_request"},
        order="revision_no.desc",
        limit=1,
    )
    revision_no = int(documents.data[0].get("revision_no") or 0) + 1 if documents.data else 1
    snapshot = await _offer_request_snapshot(project_id, workflow, payload, token, gateway)
    created = await gateway.insert(
        "workflow_documents",
        token,
        {
            "project_id": project_id,
            "workflow_id": workflow_id,
            "document_type": "offer_request",
            "revision_no": revision_no,
            "title": snapshot["title"],
            "data": snapshot,
        },
    )
    if created:
        return created[0]
    refreshed = await gateway.select(
        "workflow_documents",
        token,
        filters={
            "project_id": f"eq.{project_id}",
            "workflow_id": f"eq.{workflow_id}",
            "document_type": "eq.offer_request",
            "revision_no": f"eq.{revision_no}",
        },
        order="id.desc",
        limit=1,
    )
    if not refreshed.data:
        raise UpstreamError("A dokumentum létrejött, de nem tölthető vissza.")
    return refreshed.data[0]


@router.put("/{project_id}/workflows/{workflow_id}/documents/{document_id}")
async def update_offer_request_document(
    project_id: int,
    workflow_id: int,
    document_id: int,
    payload: OfferRequestDocumentWrite,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("subcontractor_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    workflow = await _workflow_for_document(project_id, workflow_id, token, gateway)
    documents = await gateway.select(
        "workflow_documents",
        token,
        filters={
            "id": f"eq.{document_id}",
            "project_id": f"eq.{project_id}",
            "workflow_id": f"eq.{workflow_id}",
            "document_type": "eq.offer_request",
        },
        limit=1,
    )
    if not documents.data:
        raise NotFoundError("A dokumentum nem található.")
    if documents.data[0].get("status") != "draft":
        raise ConflictError("Kiadott dokumentum nem módosítható. Készíts új változatot.")
    snapshot = await _offer_request_snapshot(project_id, workflow, payload, token, gateway)
    updated = await gateway.update(
        "workflow_documents",
        token,
        {"title": snapshot["title"], "data": snapshot},
        {"id": f"eq.{document_id}", "project_id": f"eq.{project_id}", "workflow_id": f"eq.{workflow_id}"},
    )
    if updated:
        return updated[0]
    return await _saved_offer_request_document(
        project_id,
        workflow_id,
        document_id,
        token,
        gateway,
    )


@router.post("/{project_id}/workflows/{workflow_id}/documents/{document_id}/issue")
async def issue_offer_request_document(
    project_id: int,
    workflow_id: int,
    document_id: int,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("subcontractor_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict:
    workflow = await _workflow_for_document(project_id, workflow_id, token, gateway)
    if int(workflow.get("current_step") or 1) != 2:
        raise ConflictError("Az ajánlatkérő csak a folyamat 2. lépésében adható ki.")
    documents = await gateway.select(
        "workflow_documents",
        token,
        filters={
            "id": f"eq.{document_id}",
            "project_id": f"eq.{project_id}",
            "workflow_id": f"eq.{workflow_id}",
            "document_type": "eq.offer_request",
        },
        limit=1,
    )
    if not documents.data:
        raise NotFoundError("A dokumentum nem található.")
    document = documents.data[0]
    if document.get("status") != "draft":
        raise ConflictError("Csak piszkozat státuszú dokumentum adható ki.")
    await gateway.update(
        "workflow_documents",
        token,
        {"status": "superseded"},
        {"project_id": f"eq.{project_id}", "workflow_id": f"eq.{workflow_id}", "document_type": "eq.offer_request", "status": "eq.issued"},
    )
    issued_at = datetime.now(timezone.utc).isoformat()
    issued = await gateway.update(
        "workflow_documents",
        token,
        {"status": "issued", "issued_at": issued_at},
        {"id": f"eq.{document_id}", "project_id": f"eq.{project_id}", "workflow_id": f"eq.{workflow_id}"},
    )
    document_date = _as_iso_date((document.get("data") or {}).get("document_date")) or date.today().isoformat()
    await gateway.update(
        "subcontractor_workflows",
        token,
        {"offer_status": "Kiküldve", "offer_date": document_date},
        {"id": f"eq.{workflow_id}", "project_id": f"eq.{project_id}"},
    )
    return issued[0]


@router.get("/{project_id}/workflows/{workflow_id}/documents/{document_id}/preview")
async def preview_offer_request_document(
    project_id: int,
    workflow_id: int,
    document_id: int,
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> Response:
    document = await _offer_request_document_for_export(
        project_id,
        workflow_id,
        document_id,
        token,
        gateway,
    )
    return _offer_request_file_response(document, workflow_id, "pdf", inline=True)


@router.get("/{project_id}/workflows/{workflow_id}/documents/{document_id}/export")
async def export_offer_request_document(
    project_id: int,
    workflow_id: int,
    document_id: int,
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
    format: Literal["pdf", "word"] = "pdf",
) -> Response:
    document = await _offer_request_document_for_export(
        project_id,
        workflow_id,
        document_id,
        token,
        gateway,
    )
    return _offer_request_file_response(document, workflow_id, format, inline=False)


@router.get("/{project_id}/workflows/{workflow_id}/documents/{document_id}/pdf")
async def download_offer_request_document(
    project_id: int,
    workflow_id: int,
    document_id: int,
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
    preview: bool = False,
) -> Response:
    """Backward-compatible PDF route retained for existing bookmarks and clients."""
    document = await _offer_request_document_for_export(
        project_id,
        workflow_id,
        document_id,
        token,
        gateway,
    )
    return _offer_request_file_response(document, workflow_id, "pdf", inline=preview)


@router.get("/{project_id}/workflows/{workflow_id}")
async def workflow_detail(project_id: int, workflow_id: int, token: AccessToken, _: AuthenticatedUser, gateway: Annotated[SupabaseGateway, Depends(get_gateway)]) -> dict:
    workflow, offer_parts, contract_parts, changes, key_assignments = await asyncio.gather(
        gateway.select("subcontractor_workflows", token, filters={"id": f"eq.{workflow_id}", "project_id": f"eq.{project_id}", "is_deleted": "eq.false"}, limit=1),
        gateway.select("offer_parts", token, filters={"workflow_id": f"eq.{workflow_id}"}, order="id.asc"),
        gateway.select("contract_parts", token, filters={"workflow_id": f"eq.{workflow_id}"}, order="id.asc"),
        gateway.select("contract_changes", token, filters={"workflow_id": f"eq.{workflow_id}"}, order="change_date.asc,id.asc"),
        _optional_table_rows(
            gateway,
            "subcontractor_workflow_schedule_keys",
            token,
            filters={"project_id": f"eq.{project_id}", "workflow_id": f"eq.{workflow_id}"},
            order="financial_phase_no.asc,schedule_key_id.asc,id.asc",
        ),
    )
    if not workflow.data:
        raise NotFoundError("Az alvállalkozói folyamat nem található.")
    return {
        **workflow.data[0],
        "offer_parts": offer_parts.data,
        "contract_parts": contract_parts.data,
        "contract_changes": changes.data,
        "schedule_key_assignments": key_assignments,
    }


@router.put("/{project_id}/workflows/{workflow_id}/schedule-keys")
async def replace_workflow_schedule_keys(
    project_id: int,
    workflow_id: int,
    payload: WorkflowScheduleKeyAssignments,
    token: AccessToken,
    _: CsrfProtected,
    __=Depends(require_permission("subcontractor_write")),
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None,
) -> dict[str, list[dict]]:
    await ensure_project_access(gateway, token, project_id, write=True)
    workflow = await gateway.select(
        "subcontractor_workflows",
        token,
        filters={"id": f"eq.{workflow_id}", "project_id": f"eq.{project_id}", "is_deleted": "eq.false"},
        limit=1,
    )
    if not workflow.data:
        raise NotFoundError("Az alvallalkozoi folyamat nem talalhato.")
    await gateway.rpc(
        "replace_subcontractor_workflow_schedule_keys",
        token,
        {
            "target_project_id": project_id,
            "target_workflow_id": workflow_id,
            "requested_assignments": [
                item.model_dump(mode="json") for item in payload.assignments
            ],
        },
    )
    assignments = await _optional_table_rows(
        gateway,
        "subcontractor_workflow_schedule_keys",
        token,
        filters={"project_id": f"eq.{project_id}", "workflow_id": f"eq.{workflow_id}"},
        order="financial_phase_no.asc,schedule_key_id.asc,id.asc",
    )
    return {"assignments": assignments}


@router.post("/{project_id}/workflows")
async def create_workflow(project_id: int, payload: WorkflowCreate, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("subcontractor_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict:
    data = normalize_workflow_money(payload.model_dump(mode="json"))
    data["project_id"] = project_id
    data["current_step"] = 1
    result = await gateway.insert("subcontractor_workflows", token, data)
    await _sync_single_part_bases(project_id, result[0], token, gateway)
    return result[0]


@router.put("/{project_id}/workflows/{workflow_id}")
async def update_workflow(project_id: int, workflow_id: int, payload: WorkflowUpdate, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("subcontractor_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict:
    existing = await gateway.select("subcontractor_workflows", token, filters={"id": f"eq.{workflow_id}", "project_id": f"eq.{project_id}", "is_deleted": "eq.false"}, limit=1)
    if not existing.data:
        raise NotFoundError("Az alvállalkozói folyamat nem található.")
    allow_reopen = payload.reopen_completed_payments
    data = normalize_workflow_money(payload.model_dump(mode="json"))
    data["project_id"] = project_id
    data["current_step"] = int(existing.data[0].get("current_step") or 1)
    candidate = {**existing.data[0], **data, "id": workflow_id}
    await _sync_single_part_bases(project_id, candidate, token, gateway, allow_reopen=allow_reopen, apply=False)
    result = await gateway.update("subcontractor_workflows", token, data, {"id": f"eq.{workflow_id}", "project_id": f"eq.{project_id}"})
    reopened = await _sync_single_part_bases(project_id, result[0], token, gateway, allow_reopen=allow_reopen)
    if reopened:
        result[0]["reopened_payments"] = reopened
    return result[0]


@router.post("/{project_id}/workflows/{workflow_id}/step")
async def transition_workflow_step(project_id: int, workflow_id: int, payload: WorkflowStepRequest, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("subcontractor_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict:
    workflow_result = await gateway.select("subcontractor_workflows", token, filters={"id": f"eq.{workflow_id}", "project_id": f"eq.{project_id}", "is_deleted": "eq.false"}, limit=1)
    if not workflow_result.data:
        raise NotFoundError("Az alvállalkozói folyamat nem található.")
    workflow = workflow_result.data[0]
    current_step = int(workflow.get("current_step") or 1)
    if payload.action == "close":
        if payload.step != current_step:
            raise ConflictError("Csak az aktuálisan nyitott lépés zárható le.")
        offer_parts = await gateway.select("offer_parts", token, filters={"workflow_id": f"eq.{workflow_id}"}, order="id.asc")
        try:
            warnings = validate_step_close(
                workflow,
                offer_parts.data,
                payload.step,
                allow_offer_mismatch=payload.allow_offer_mismatch,
            )
        except ValueError as exc:
            raise ConflictError(str(exc)) from exc
        next_step = payload.step + 1
    else:
        if payload.step >= current_step:
            raise ConflictError("Csak egy korábban lezárt lépés nyitható újra.")
        warnings = []
        next_step = payload.step
    result = await gateway.update("subcontractor_workflows", token, {"current_step": next_step}, {"id": f"eq.{workflow_id}", "project_id": f"eq.{project_id}"})
    refreshed = result[0]
    await _sync_single_part_bases(project_id, refreshed, token, gateway)
    return {**refreshed, "warnings": warnings}


@router.delete("/{project_id}/workflows/{workflow_id}")
async def archive_workflow(project_id: int, workflow_id: int, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("subcontractor_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict[str, bool]:
    payments = await gateway.select("payments", token, filters={"project_id": f"eq.{project_id}", "workflow_id": f"eq.{workflow_id}"}, limit=1)
    matrix_cells = await gateway.select("contract_matrix", token, filters={"project_id": f"eq.{project_id}"})
    workflow_prefix = f"ALV_{workflow_id}_"
    has_allocation = any(
        str(cell.get("reference_id") or "").upper().startswith(workflow_prefix)
        and Decimal(str(cell.get("amount") or 0)) != 0
        for cell in matrix_cells.data
    )
    if payments.data or has_allocation:
        raise ConflictError("Az alvállalkozói folyamat nem archiválható, amíg mátrixkiosztás vagy pénzügyi rögzítés hivatkozik rá.")
    await gateway.update("subcontractor_workflows", token, {"is_deleted": True}, {"id": f"eq.{workflow_id}", "project_id": f"eq.{project_id}"})
    return {"archived": True}


@router.put("/{project_id}/workflows/{workflow_id}/offer-parts")
async def replace_offer_parts(project_id: int, workflow_id: int, parts: list[OfferPart], token: AccessToken, _: CsrfProtected, __=Depends(require_permission("subcontractor_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> list[dict]:
    workflow = await gateway.select("subcontractor_workflows", token, filters={"id": f"eq.{workflow_id}", "project_id": f"eq.{project_id}"}, limit=1)
    if not workflow.data:
        raise NotFoundError("Az alvállalkozói folyamat nem található.")
    await gateway.delete("offer_parts", token, {"workflow_id": f"eq.{workflow_id}"})
    if not parts:
        return []
    return await gateway.insert("offer_parts", token, [dict(part.model_dump(mode="json"), workflow_id=workflow_id) for part in parts])


@router.put("/{project_id}/workflows/{workflow_id}/contract-parts")
async def replace_contract_parts(project_id: int, workflow_id: int, parts: list[ContractPart], token: AccessToken, _: CsrfProtected, __=Depends(require_permission("subcontractor_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> list[dict]:
    workflow = await gateway.select("subcontractor_workflows", token, filters={"id": f"eq.{workflow_id}", "project_id": f"eq.{project_id}"}, limit=1)
    if not workflow.data:
        raise NotFoundError("Az alvállalkozói folyamat nem található.")
    await gateway.delete("contract_parts", token, {"workflow_id": f"eq.{workflow_id}"})
    if not parts:
        return []
    return await gateway.insert("contract_parts", token, [dict(part.model_dump(mode="json"), workflow_id=workflow_id) for part in parts])


@router.post("/{project_id}/workflows/{workflow_id}/changes")
async def create_contract_change(project_id: int, workflow_id: int, change: ContractChangeCreate, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("subcontractor_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict:
    workflow = await gateway.select("subcontractor_workflows", token, filters={"id": f"eq.{workflow_id}", "project_id": f"eq.{project_id}"}, limit=1)
    if not workflow.data:
        raise NotFoundError("Az alvállalkozói folyamat nem található.")
    allow_reopen = change.reopen_completed_payments
    data = change.model_dump(mode="json", exclude={"reopen_completed_payments"})
    data["workflow_id"] = workflow_id
    refreshed = {**workflow.data[0], **data, "id": workflow_id}
    await _sync_single_part_bases(project_id, refreshed, token, gateway, allow_reopen=allow_reopen, apply=False)
    result = await gateway.insert("contract_changes", token, data)
    await gateway.update("subcontractor_workflows", token, {
        "modified_fee": data["modified_fee"],
        "modified_copyright_fee": data["modified_copyright_fee"],
        "modified_total": data["modified_total"],
        "modification_date": data["change_date"] or "",
        "modification_note": data["reason"],
    }, {"id": f"eq.{workflow_id}", "project_id": f"eq.{project_id}"})
    reopened = await _sync_single_part_bases(project_id, refreshed, token, gateway, allow_reopen=allow_reopen)
    return {**result[0], "reopened_payments": reopened}


@router.delete("/{project_id}/workflows/{workflow_id}/changes/{change_id}")
async def delete_contract_change(project_id: int, workflow_id: int, change_id: int, token: AccessToken, _: CsrfProtected, reopen_completed_payments: bool = False, __=Depends(require_permission("subcontractor_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict[str, object]:
    workflow = await gateway.select("subcontractor_workflows", token, filters={"id": f"eq.{workflow_id}", "project_id": f"eq.{project_id}"}, limit=1)
    if not workflow.data:
        raise NotFoundError("Az alvállalkozói folyamat nem található.")
    changes = await gateway.select("contract_changes", token, filters={"workflow_id": f"eq.{workflow_id}"}, order="change_date.desc,id.desc")
    latest = next((item for item in changes.data if int(item.get("id") or 0) != change_id), {})
    restored = {
        "modified_fee": latest.get("modified_fee", ""),
        "modified_copyright_fee": latest.get("modified_copyright_fee", ""),
        "modified_total": latest.get("modified_total", ""),
        "modification_date": latest.get("change_date") or "",
        "modification_note": latest.get("reason", ""),
    }
    candidate = {**workflow.data[0], **restored}
    await _sync_single_part_bases(project_id, candidate, token, gateway, allow_reopen=reopen_completed_payments, apply=False)
    await gateway.delete("contract_changes", token, {"id": f"eq.{change_id}", "workflow_id": f"eq.{workflow_id}"})
    await gateway.update("subcontractor_workflows", token, restored, {"id": f"eq.{workflow_id}", "project_id": f"eq.{project_id}"})
    reopened = await _sync_single_part_bases(project_id, candidate, token, gateway, allow_reopen=reopen_completed_payments)
    return {"deleted": True, "reopened_payments": reopened}


@router.get("/{project_id}/matrix")
async def matrix(project_id: int, token: AccessToken, _: AuthenticatedUser, gateway: Annotated[SupabaseGateway, Depends(get_gateway)]) -> dict[str, object]:
    stages, milestones, sections, cells, base, workflows, payments, project = await asyncio.gather(
        gateway.select("contract_stages", token, filters={"project_id": f"eq.{project_id}"}, order="sort_order.asc,id.asc"),
        gateway.select("project_milestones", token, filters={"project_id": f"eq.{project_id}"}, order="planned_date.asc,sequence_no.asc,id.asc"),
        gateway.select("project_contract_sections", token, filters={"project_id": f"eq.{project_id}"}, order="section_no.asc,id.asc"),
        gateway.select("contract_matrix", token, filters={"project_id": f"eq.{project_id}"}),
        gateway.select("contract_base_values", token, filters={"project_id": f"eq.{project_id}"}),
        gateway.select("subcontractor_workflows", token, filters={"project_id": f"eq.{project_id}", "is_deleted": "eq.false"}, order="display_order.asc,id.asc"),
        gateway.select("payments", token, filters={"project_id": f"eq.{project_id}", "status": "eq.Pénzügyileg teljesítve"}),
        gateway.select("projects", token, filters={"id": f"eq.{project_id}", "is_deleted": "eq.false"}, limit=1),
    )
    fallback_date = _as_iso_date((project.data[0] if project.data else {}).get("created_at")) or date.today().isoformat()
    columns, matrix_warnings = _strict_matrix_columns(
        milestones.data,
        stages.data,
        cells.data,
        fallback_date,
    )
    if matrix_warnings:
        logger.warning(
            "matrix_date_quality project_id=%s warning_count=%s warnings=%s",
            project_id,
            len(matrix_warnings),
            " | ".join(matrix_warnings),
        )
    paid_references = {
        str(item.get("reference") or "").upper(): {
            "payment_id": item.get("id"),
            "amount": item.get("amount", 0),
            "status": item.get("status", ""),
        }
        for item in payments.data
        if str(item.get("reference") or "").upper().startswith("KIA_WF_")
    }
    return {
        "columns": columns,
        "matrix_warnings": matrix_warnings,
        "stages": stages.data,
        "milestones": milestones.data,
        "contract_sections": sections.data,
        "cells": cells.data,
        "base_values": base.data,
        "workflows": workflows.data,
        "paid_references": paid_references,
    }


@router.get("/{project_id}/workspace")
async def subcontractor_workspace(
    project_id: int,
    token: AccessToken,
    user: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> dict[str, object]:
    workflows, matrix_data, catalog = await asyncio.gather(
        list_workflows(project_id, token, user, gateway),
        matrix(project_id, token, user, gateway),
        subcontractor_catalog(project_id, token, user, gateway),
    )
    return {
        "workflows": workflows,
        "matrix": matrix_data,
        "catalog": catalog,
    }


@router.post("/{project_id}/matrix/stages")
async def create_matrix_stage(project_id: int, stage: ContractStageCreate, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("subcontractor_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict:
    result = await gateway.insert("contract_stages", token, dict(stage.model_dump(mode="json"), project_id=project_id))
    return result[0]


@router.put("/{project_id}/matrix/stages/{stage_id}")
async def update_matrix_stage(project_id: int, stage_id: int, stage: ContractStageCreate, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("subcontractor_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict:
    result = await gateway.update("contract_stages", token, stage.model_dump(mode="json"), {"id": f"eq.{stage_id}", "project_id": f"eq.{project_id}"})
    if not result:
        raise NotFoundError("A mátrixoszlop nem található.")
    return result[0]


@router.delete("/{project_id}/matrix/stages/{stage_id}")
async def delete_matrix_stage(project_id: int, stage_id: int, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("subcontractor_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict[str, bool]:
    payment_reference_suffix = f"_COL_STAGE_{stage_id}"
    payments = await gateway.select("payments", token, filters={"project_id": f"eq.{project_id}"})
    if any(str(payment.get("reference") or "").upper().endswith(payment_reference_suffix) for payment in payments.data):
        raise ConflictError("Az ütemezési oszlop nem törölhető, mert pénzügyi folyamat hivatkozik rá.")
    await gateway.delete("contract_stages", token, {"id": f"eq.{stage_id}", "project_id": f"eq.{project_id}"})
    return {"deleted": True}


@router.put("/{project_id}/matrix/base-values")
async def save_matrix_base_values(project_id: int, values: list[ContractBaseValue], token: AccessToken, _: CsrfProtected, __=Depends(require_permission("subcontractor_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict[str, list[dict]]:
    if not values:
        return {"base_values": [], "cells": [], "reopened_payments": []}
    affected: list[tuple[ContractBaseValue, dict, Decimal]] = []
    payment_references: set[str] = set()
    for value in values:
        cells = await gateway.select("contract_matrix", token, filters={"project_id": f"eq.{project_id}", "reference_id": f"eq.{value.reference_id}"})
        base = Decimal(str(value.amount or 0))
        for cell in cells.data:
            if cell.get("percent") is None:
                continue
            amount = (base * Decimal(str(cell.get("percent") or 0)) / Decimal("100")).quantize(Decimal("0.01"))
            if abs(amount - Decimal(str(cell.get("amount") or 0))) < Decimal("0.01"):
                continue
            affected.append((value, cell, amount))
            reference = matrix_payment_reference(value.reference_id, str(cell.get("column_code") or ""))
            if reference:
                payment_references.add(reference)
    completed = await gateway.select("payments", token, filters={"project_id": f"eq.{project_id}", "status": "eq.Pénzügyileg teljesítve"})
    impacted = [item for item in completed.data if str(item.get("reference") or "").upper() in payment_references]
    if impacted and not all(value.reopen_completed_payments for value in values):
        raise ConflictError(
            "A bázis módosítása pénzügyileg teljesített tételeket érint. A mentéshez jóvá kell hagyni a pénzügyi státuszok visszanyitását.",
            detail={"requires_reopen": True, "payment_ids": [item.get("id") for item in impacted]},
        )
    payload = [dict(value.model_dump(mode="json", exclude={"reopen_completed_payments"}), project_id=project_id) for value in values]
    saved_bases = await gateway.upsert("contract_base_values", token, payload, on_conflict="project_id,reference_id")
    saved_cells: list[dict] = []
    for _, cell, amount in affected:
        result = await gateway.update("contract_matrix", token, {"amount": float(amount)}, {"id": f"eq.{cell['id']}", "project_id": f"eq.{project_id}"})
        saved_cells.extend(result)
    reopened: list[dict] = []
    for payment in impacted:
        await gateway.update("payments", token, {"status": "Várható", "payment_date": None}, {"id": f"eq.{payment['id']}", "project_id": f"eq.{project_id}"})
        reopened.append({"payment_id": payment.get("id"), "reference": payment.get("reference"), "old_amount": payment.get("amount", 0)})
    return {"base_values": saved_bases, "cells": saved_cells, "reopened_payments": reopened}


@router.put("/{project_id}/matrix")
async def save_matrix(project_id: int, cells: list[ContractMatrixCell], token: AccessToken, _: CsrfProtected, __=Depends(require_permission("subcontractor_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict[str, list[dict]]:
    saved: list[dict] = []
    reopened: list[dict] = []
    for cell in cells:
        result, reopened_payment = await _save_matrix_cell(project_id, cell, token, gateway)
        saved.append(result)
        if reopened_payment:
            reopened.append(reopened_payment)
    return {"cells": saved, "reopened_payments": reopened}


@router.put("/{project_id}/matrix/{cell_id}")
async def update_matrix_cell(project_id: int, cell_id: int, cell: ContractMatrixCell, token: AccessToken, _: CsrfProtected, __=Depends(require_permission("subcontractor_write")), gateway: Annotated[SupabaseGateway, Depends(get_gateway)] = None) -> dict:
    result, reopened = await _save_matrix_cell(project_id, cell, token, gateway, cell_id=cell_id)
    return {"cell": result, "reopened_payments": [reopened] if reopened else []}
