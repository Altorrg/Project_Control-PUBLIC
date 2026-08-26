from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import Field, model_validator

from ..hitelesites import AccessToken, AuthenticatedUser, CsrfProtected, get_gateway
from ..adatmodellek.kozos import ApiModel
from ..hibak import NotFoundError
from ..jogosultsagok import ensure_project_access
from ..supabase_kapcsolat import SupabaseGateway


router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationDismiss(ApiModel):
    alert_key: str = Field(min_length=1, max_length=500)
    mode: Literal["snooze", "forever"]
    days: int | None = Field(default=None, ge=1, le=3650)


class NotificationAction(ApiModel):
    alert_key: str = Field(min_length=1, max_length=500)
    action: Literal["skip_15", "defer_24", "custom", "forever", "priority"]
    remind_at: datetime | None = None
    priority: int | None = Field(default=None, ge=1, le=4)

    @model_validator(mode="after")
    def validate_action_details(self) -> "NotificationAction":
        if self.action == "custom" and self.remind_at is None:
            raise ValueError("Az egyedi értesítési időpont megadása kötelező.")
        if self.action == "priority" and self.priority is None:
            raise ValueError("A prioritás megadása kötelező.")
        return self


NotificationTarget = Literal[
    "settings", "disciplines", "schedule", "subcontractors",
    "finance", "engagements", "admin",
]


class NotificationTaskCreate(ApiModel):
    title: str = Field(min_length=1, max_length=255)
    details: str = Field(default="", max_length=5000)
    due_date: date
    due_time: time | None = None
    priority: int = Field(default=2, ge=1, le=4)
    project_id: int | None = Field(default=None, gt=0)
    target_module: NotificationTarget | None = None


class NotificationTaskFromNotification(ApiModel):
    alert_key: str = Field(min_length=1, max_length=500)
    priority: int = Field(default=2, ge=1, le=4)


class NotificationTaskUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    details: str | None = Field(default=None, max_length=5000)
    due_date: date | None = None
    due_time: time | None = None
    priority: int | None = Field(default=None, ge=1, le=4)
    project_id: int | None = Field(default=None, gt=0)
    target_module: NotificationTarget | None = None
    completed: bool | None = None


def _single_row(result: object) -> dict:
    if isinstance(result, list):
        return dict(result[0]) if result else {}
    return dict(result) if isinstance(result, dict) else {}


def _application_date(result: object) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, list) and result:
        return _application_date(result[0])
    if isinstance(result, dict) and result:
        return str(next(iter(result.values())))
    return date.today().isoformat()


async def _system_notifications(gateway: SupabaseGateway, token: str) -> list[dict]:
    rows = await gateway.rpc("current_notifications", token) or []
    try:
        weekly_rows = await gateway.rpc("weekly_completed_task_notifications", token) or []
    except NotFoundError:
        # A normal ertesitesi lista a migracio telepitese elott is hasznalhato marad.
        weekly_rows = []
    return [dict(row) for row in [*rows, *weekly_rows] if isinstance(row, dict)]


@router.get("")
async def list_notifications(token: AccessToken, user: AuthenticatedUser, gateway: Annotated[SupabaseGateway, Depends(get_gateway)]) -> list[dict]:
    rows = await _system_notifications(gateway, token)
    notifications = [
        {
            **dict(row),
            "priority": int(row.get("priority") or 2),
            "target_module": row.get("target_module"),
            "target_id": row.get("target_id"),
            "due_date": row.get("due_date"),
        }
        for row in rows
        if isinstance(row, dict)
    ]

    application_date = _application_date(await gateway.rpc("app_today", token))
    overdue_response = await gateway.select(
        "notification_tasks",
        token,
        filters={
            "profile_id": f"eq.{user.id}",
            "due_date": f"lt.{application_date}",
            "completed_at": "is.null",
        },
        order="priority.asc,due_date.asc,due_time.asc.nullslast,created_at.asc",
        limit=100,
    )
    overdue_tasks = [dict(row) for row in (overdue_response.data or []) if isinstance(row, dict)]
    alert_keys = [f"task-overdue:{task['id']}" for task in overdue_tasks if task.get("id") is not None]
    dismissals: dict[str, dict] = {}
    if alert_keys:
        dismissal_response = await gateway.select(
            "notification_dismissals",
            token,
            filters={
                "profile_id": f"eq.{user.id}",
                "alert_key": f"in.({','.join(alert_keys)})",
            },
        )
        dismissals = {
            str(row.get("alert_key")): dict(row)
            for row in (dismissal_response.data or [])
            if isinstance(row, dict) and row.get("alert_key")
        }

    now = datetime.now(timezone.utc)
    for task in overdue_tasks:
        alert_key = f"task-overdue:{task['id']}"
        dismissal = dismissals.get(alert_key)
        if dismissal:
            if dismissal.get("dismiss_mode") == "forever":
                continue
            snooze_until = dismissal.get("snooze_until")
            if snooze_until:
                try:
                    parsed = datetime.fromisoformat(str(snooze_until).replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    if parsed > now:
                        continue
                except ValueError:
                    pass
        priority = int((dismissal or {}).get("priority") or task.get("priority") or 2)
        notifications.append({
            "alert_key": alert_key,
            "project_id": task.get("project_id"),
            "project_name": "",
            "subject": task.get("title") or "Lejárt napi teendő",
            "message": f"Határidő: {task.get('due_date')}. " + (task.get("details") or "A teendő még nincs készre jelölve."),
            "alert_type": "task_overdue",
            "target_module": task.get("target_module"),
            "target_id": task.get("id"),
            "due_date": task.get("due_date"),
            "priority": priority,
        })
    return sorted(notifications, key=lambda item: (int(item.get("priority") or 2), str(item.get("due_date") or ""), str(item.get("subject") or "")))


@router.get("/date")
async def current_application_date(
    token: AccessToken,
    _: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> dict[str, str | bool]:
    application_date = _application_date(await gateway.rpc("app_today", token))
    system_date = date.today().isoformat()
    return {
        "system_date": system_date,
        "application_date": application_date,
        "is_test_date": application_date != system_date,
    }


@router.post("/action")
async def apply_action(
    payload: NotificationAction,
    token: AccessToken,
    _: CsrfProtected,
    user: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> dict:
    remind_at = payload.remind_at
    if remind_at is not None and remind_at.tzinfo is None:
        remind_at = remind_at.replace(tzinfo=timezone.utc)
    result = await gateway.rpc(
        "notification_action",
        token,
        {
            "target_alert_key": payload.alert_key,
            "action_name": payload.action,
            "remind_at": remind_at.isoformat() if remind_at else None,
            "priority_value": payload.priority,
        },
    )
    return _single_row(result)


@router.get("/tasks/today")
async def list_today_tasks(
    token: AccessToken,
    user: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> list[dict]:
    application_date = _application_date(await gateway.rpc("app_today", token))
    response = await gateway.select(
        "notification_tasks",
        token,
        filters={
            "profile_id": f"eq.{user.id}",
            "due_date": f"eq.{application_date}",
            "completed_at": "is.null",
        },
        order="priority.asc,due_time.asc.nullslast,created_at.asc",
    )
    return response.data or []


@router.get("/tasks/history")
async def list_task_history(
    token: AccessToken,
    user: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> list[dict]:
    application_date = date.fromisoformat(_application_date(await gateway.rpc("app_today", token)))
    history_start = application_date - timedelta(days=31)
    response = await gateway.select(
        "notification_tasks",
        token,
        filters={
            "profile_id": f"eq.{user.id}",
            "and": f"(due_date.gte.{history_start.isoformat()},due_date.lte.{application_date.isoformat()})",
        },
        order="due_date.desc,due_time.asc.nullslast,created_at.desc",
        limit=500,
    )
    return response.data or []


@router.post("/tasks")
async def create_task(
    payload: NotificationTaskCreate,
    token: AccessToken,
    _: CsrfProtected,
    user: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> dict:
    if payload.project_id is not None:
        await ensure_project_access(gateway, token, payload.project_id)
    data = payload.model_dump(mode="json")
    data["profile_id"] = user.id
    return _single_row(await gateway.insert("notification_tasks", token, data))


@router.post("/tasks/from-notification")
async def move_notification_to_task(
    payload: NotificationTaskFromNotification,
    token: AccessToken,
    _: CsrfProtected,
    user: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> dict:
    notifications = await _system_notifications(gateway, token)
    notification = next(
        (
            dict(row)
            for row in notifications
            if isinstance(row, dict) and row.get("alert_key") == payload.alert_key
        ),
        None,
    )
    if notification is None:
        raise NotFoundError("Az értesítés már nem aktív vagy nem található.")

    project_id = notification.get("project_id")
    if project_id is not None:
        project_id = int(project_id)
        await ensure_project_access(gateway, token, project_id)

    target_module = notification.get("target_module")
    if target_module not in NotificationTarget.__args__:
        target_module = "settings" if project_id is not None else None

    application_date = _application_date(await gateway.rpc("app_today", token))
    task = _single_row(
        await gateway.insert(
            "notification_tasks",
            token,
            {
                "profile_id": user.id,
                "project_id": project_id,
                "title": str(notification.get("subject") or "Értesítésből létrehozott teendő")[:255],
                "details": str(notification.get("message") or "")[:5000],
                "due_date": application_date,
                "due_time": None,
                "priority": payload.priority,
                "target_module": target_module,
                "source_alert_key": str(notification.get("source_alert_key") or payload.alert_key)[:500],
            },
        )
    )
    if not task:
        raise NotFoundError("A napi teendő nem hozható létre.")

    try:
        await gateway.rpc(
            "notification_action",
            token,
            {
                "target_alert_key": payload.alert_key,
                "action_name": "forever",
                "remind_at": None,
                "priority_value": payload.priority,
            },
        )
    except Exception:
        await gateway.delete(
            "notification_tasks",
            token,
            {"id": f"eq.{task['id']}", "profile_id": f"eq.{user.id}"},
        )
        raise
    return task


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: int,
    payload: NotificationTaskUpdate,
    token: AccessToken,
    _: CsrfProtected,
    user: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> dict:
    data = payload.model_dump(mode="json", exclude_unset=True)
    completed = data.pop("completed", None)
    if "project_id" in data and data["project_id"] is not None:
        await ensure_project_access(gateway, token, int(data["project_id"]))
    if completed is not None:
        data["completed_at"] = datetime.now(timezone.utc).isoformat() if completed else None
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await gateway.update(
        "notification_tasks",
        token,
        data,
        {"id": f"eq.{task_id}", "profile_id": f"eq.{user.id}"},
    )
    row = _single_row(result)
    if not row:
        raise NotFoundError("A teendő nem található.")
    return row


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: int,
    token: AccessToken,
    _: CsrfProtected,
    user: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> dict[str, bool]:
    result = await gateway.delete(
        "notification_tasks",
        token,
        {"id": f"eq.{task_id}", "profile_id": f"eq.{user.id}"},
    )
    if not result:
        raise NotFoundError("A teendő nem található.")
    return {"deleted": True}


@router.post("/dismiss")
async def dismiss(payload: NotificationDismiss, token: AccessToken, _: CsrfProtected, user: AuthenticatedUser, gateway: Annotated[SupabaseGateway, Depends(get_gateway)]) -> dict:
    result = await gateway.rpc("dismiss_notification", token, {"alert_key": payload.alert_key, "dismiss_mode": payload.mode, "snooze_days": payload.days})
    return result[0] if isinstance(result, list) and result else result


@router.post("/{alert_key}/read")
async def mark_read(
    alert_key: str,
    token: AccessToken,
    _: CsrfProtected,
    user: AuthenticatedUser,
    gateway: Annotated[SupabaseGateway, Depends(get_gateway)],
) -> dict[str, object]:
    # The generated alert key identifies one concrete event. A permanent
    # dismissal of that key is therefore the persisted "read" state.
    await gateway.rpc(
        "dismiss_notification",
        token,
        {"alert_key": alert_key, "dismiss_mode": "forever", "snooze_days": None},
    )
    return {"alert_key": alert_key, "is_read": True}


@router.delete("/{alert_key}")
async def clear(alert_key: str, token: AccessToken, _: CsrfProtected, user: AuthenticatedUser, gateway: Annotated[SupabaseGateway, Depends(get_gateway)]) -> dict[str, bool]:
    await gateway.delete("notification_dismissals", token, {"profile_id": f"eq.{user.id}", "alert_key": f"eq.{alert_key}"})
    return {"deleted": True}
