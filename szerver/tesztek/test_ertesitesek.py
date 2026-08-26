from __future__ import annotations

from datetime import date
from types import SimpleNamespace
import unittest

from pydantic import ValidationError

from alkalmazas.hitelesites import CurrentUser
from alkalmazas.vegpontok.ertesitesek import (
    NotificationAction,
    NotificationTaskCreate,
    NotificationTaskFromNotification,
    apply_action,
    create_task,
    list_notifications,
    list_task_history,
    list_today_tasks,
    move_notification_to_task,
)


class NotificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = CurrentUser(
            id="00000000-0000-0000-0000-000000000001",
            email="editor@example.test",
            display_name="Teszt Szerkesztő",
            role="editor",
            active=True,
        )

    def test_custom_reminder_requires_a_timestamp(self) -> None:
        with self.assertRaises(ValidationError):
            NotificationAction(alert_key="eng:1", action="custom")

    def test_priority_action_requires_a_priority(self) -> None:
        with self.assertRaises(ValidationError):
            NotificationAction(alert_key="eng:1", action="priority")

    async def test_skip_action_uses_the_exact_notification_rpc(self) -> None:
        class Gateway:
            async def rpc(self, function_name, token, payload):
                self.call = (function_name, token, payload)
                return [{"alert_key": payload["target_alert_key"]}]

        gateway = Gateway()
        result = await apply_action(
            NotificationAction(alert_key="eng:7", action="skip_15"),
            "jwt",
            None,
            self.user,
            gateway,
        )
        self.assertEqual(result["alert_key"], "eng:7")
        self.assertEqual(gateway.call[0], "notification_action")
        self.assertEqual(gateway.call[2]["action_name"], "skip_15")
        self.assertIsNone(gateway.call[2]["remind_at"])

    async def test_today_tasks_follow_the_application_clock(self) -> None:
        class Gateway:
            async def rpc(self, function_name, token):
                self.rpc_call = (function_name, token)
                return "2026-08-07"

            async def select(self, table, token, **kwargs):
                self.select_call = (table, token, kwargs)
                return SimpleNamespace(data=[{"id": 5, "title": "Mai teendő"}])

        gateway = Gateway()
        result = await list_today_tasks("jwt", self.user, gateway)
        self.assertEqual(result[0]["id"], 5)
        self.assertEqual(gateway.select_call[2]["filters"]["due_date"], "eq.2026-08-07")
        self.assertEqual(gateway.select_call[2]["filters"]["profile_id"], f"eq.{self.user.id}")

    async def test_task_history_keeps_the_previous_31_days(self) -> None:
        class Gateway:
            async def rpc(self, function_name, token):
                return "2026-08-07"

            async def select(self, table, token, **kwargs):
                self.select_call = (table, token, kwargs)
                return SimpleNamespace(data=[{"id": 8, "completed_at": "2026-08-06T12:00:00Z"}])

        gateway = Gateway()
        result = await list_task_history("jwt", self.user, gateway)
        self.assertEqual(result[0]["id"], 8)
        self.assertEqual(
            gateway.select_call[2]["filters"]["and"],
            "(due_date.gte.2026-07-07,due_date.lte.2026-08-07)",
        )

    async def test_overdue_open_task_is_returned_as_a_notification(self) -> None:
        class Gateway:
            def __init__(self):
                self.select_count = 0

            async def rpc(self, function_name, token):
                return [] if function_name == "current_notifications" else "2026-08-07"

            async def select(self, table, token, **kwargs):
                self.select_count += 1
                if table == "notification_tasks":
                    return SimpleNamespace(data=[{
                        "id": 14,
                        "title": "Lejárt teendő",
                        "details": "Még el kell végezni.",
                        "due_date": "2026-08-06",
                        "priority": 1,
                        "project_id": 3,
                        "target_module": "finance",
                    }])
                return SimpleNamespace(data=[])

        result = await list_notifications("jwt", self.user, Gateway())
        self.assertEqual(result[0]["alert_key"], "task-overdue:14")
        self.assertEqual(result[0]["alert_type"], "task_overdue")
        self.assertEqual(result[0]["target_module"], "finance")

    async def test_task_creation_checks_project_access_and_owns_the_row(self) -> None:
        class Gateway:
            def __init__(self):
                self.calls = []

            async def rpc(self, function_name, token, payload):
                self.calls.append(("rpc", function_name, payload))
                return True

            async def insert(self, table, token, payload):
                self.calls.append(("insert", table, payload))
                return [{"id": 11, **payload}]

        gateway = Gateway()
        payload = NotificationTaskCreate(
            title="Havi adat rögzítése",
            due_date=date(2026, 8, 7),
            project_id=3,
            target_module="disciplines",
        )
        result = await create_task(payload, "jwt", None, self.user, gateway)
        self.assertEqual(gateway.calls[0][1], "can_access_project")
        self.assertEqual(gateway.calls[0][2]["target_project_id"], 3)
        self.assertEqual(gateway.calls[1][2]["profile_id"], self.user.id)
        self.assertNotIn("source_alert_key", gateway.calls[1][2])
        self.assertEqual(result["target_module"], "disciplines")

    async def test_weekly_recheck_is_merged_into_notifications(self) -> None:
        class Gateway:
            async def rpc(self, function_name, token):
                if function_name == "current_notifications":
                    return []
                if function_name == "weekly_completed_task_notifications":
                    return [{
                        "alert_key": "weekly:task-recheck:12:2026-32",
                        "source_alert_key": "eng:7:20260701",
                        "subject": "Újra ellenőrizendő",
                        "message": "A probléma továbbra is fennáll.",
                        "alert_type": "weekly_recheck",
                        "priority": 1,
                    }]
                return "2026-08-07"

            async def select(self, table, token, **kwargs):
                return SimpleNamespace(data=[])

        result = await list_notifications("jwt", self.user, Gateway())
        self.assertEqual(result[0]["alert_key"], "weekly:task-recheck:12:2026-32")
        self.assertEqual(result[0]["source_alert_key"], "eng:7:20260701")

    async def test_notification_can_be_moved_to_the_application_day(self) -> None:
        class Gateway:
            def __init__(self):
                self.calls = []

            async def rpc(self, function_name, token, payload=None):
                self.calls.append(("rpc", function_name, payload))
                if function_name == "current_notifications":
                    return [{
                        "alert_key": "monthly:3:9:2026-07",
                        "subject": "Havi munkaidő rögzítése",
                        "message": "Az előző hónap adatai hiányoznak.",
                        "project_id": 3,
                        "target_module": "disciplines",
                    }]
                if function_name == "weekly_completed_task_notifications":
                    return []
                if function_name == "app_today":
                    return "2026-08-07"
                if function_name == "can_access_project":
                    return True
                return [{"alert_key": payload["target_alert_key"]}]

            async def insert(self, table, token, payload):
                self.calls.append(("insert", table, payload))
                return [{"id": 12, **payload}]

            async def delete(self, table, token, filters):
                self.calls.append(("delete", table, filters))
                return []

        gateway = Gateway()
        result = await move_notification_to_task(
            NotificationTaskFromNotification(alert_key="monthly:3:9:2026-07", priority=1),
            "jwt",
            None,
            self.user,
            gateway,
        )
        self.assertEqual(result["due_date"], "2026-08-07")
        self.assertEqual(result["priority"], 1)
        self.assertEqual(result["target_module"], "disciplines")
        self.assertEqual(result["source_alert_key"], "monthly:3:9:2026-07")
        self.assertEqual(gateway.calls[-1][1], "notification_action")
        self.assertEqual(gateway.calls[-1][2]["action_name"], "forever")


if __name__ == "__main__":
    unittest.main()
