from __future__ import annotations

import unittest
from pathlib import Path

from pydantic import ValidationError
from alkalmazas.adatmodellek.projektek import Project, ProjectCreate, ProjectUpdate
from alkalmazas.hibak import ConflictError, UpstreamError
from alkalmazas.vegpontok.projektek import (
    create_project,
    get_project,
    list_projects,
    update_project,
)


class ProjectApiExtensionTests(unittest.IsolatedAsyncioTestCase):
    class IdempotentGateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []
            self.created: dict[str, tuple[dict, dict]] = {}

        async def rpc(self, function_name: str, access_token: str, arguments: dict):
            self.calls.append((function_name, arguments))
            payload = arguments["payload"]
            key = payload.get("idempotency_key")
            create_data = {
                field: value
                for field, value in payload.items()
                if field != "idempotency_key"
            }
            if key and key in self.created:
                original_data, project = self.created[key]
                if original_data != create_data:
                    raise ConflictError("Az idempotencia kulcs mar mas kereshez tartozik.")
                return [project]

            project = {"id": len(self.created) + 1, **create_data}
            if key:
                self.created[key] = (create_data, project)
            return [project]

    async def test_same_idempotency_key_returns_the_original_project(self):
        gateway = self.IdempotentGateway()
        payload = ProjectCreate(
            name="Teszt projekt",
            idempotency_key="client-action-42",
            contract_subject="Elso sor\nMasodik sor",
        )

        first = await create_project(payload, "jwt", None, object(), gateway)
        second = await create_project(payload, "jwt", None, object(), gateway)

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["contract_subject"], "Elso sor\nMasodik sor")
        self.assertEqual(
            gateway.calls[0][1]["payload"]["idempotency_key"],
            "client-action-42",
        )

    async def test_reused_idempotency_key_with_different_payload_conflicts(self):
        gateway = self.IdempotentGateway()
        await create_project(
            ProjectCreate(name="Elso projekt", idempotency_key="client-action-42"),
            "jwt",
            None,
            object(),
            gateway,
        )

        with self.assertRaises(ConflictError):
            await create_project(
                ProjectCreate(name="Masodik projekt", idempotency_key="client-action-42"),
                "jwt",
                None,
                object(),
                gateway,
            )

    async def test_old_create_clients_do_not_send_new_null_fields(self):
        gateway = self.IdempotentGateway()

        project = await create_project(
            ProjectCreate(name="Regi kliens"),
            "jwt",
            None,
            object(),
            gateway,
        )

        sent_payload = gateway.calls[0][1]["payload"]
        self.assertNotIn("idempotency_key", sent_payload)
        self.assertNotIn("contract_subject", sent_payload)
        self.assertIsNone(project["contract_subject"])

    async def test_update_can_clear_contract_subject(self):
        class Gateway:
            def __init__(self) -> None:
                self.arguments: dict | None = None

            async def rpc(self, function_name: str, access_token: str, arguments: dict):
                self.arguments = arguments
                return [{"id": arguments["target_project_id"], **arguments["payload"]}]

        gateway = Gateway()
        project = await update_project(
            7,
            ProjectUpdate(contract_subject=None),
            "jwt",
            None,
            object(),
            gateway,
        )

        self.assertEqual(gateway.arguments["payload"], {"contract_subject": None})
        self.assertIsNone(project["contract_subject"])

    async def test_list_and_detail_normalize_contract_subject_for_old_rows(self):
        class Result:
            data = [{"id": 3, "name": "Regi projekt"}]

        class Gateway:
            async def select(self, table: str, access_token: str, **kwargs):
                return Result()

        gateway = Gateway()
        projects = await list_projects("jwt", object(), gateway, search="")
        project = await get_project(3, "jwt", object(), gateway)

        self.assertIsNone(projects[0]["contract_subject"])
        self.assertIsNone(project["contract_subject"])
        self.assertIsNone(Project.model_validate(project).contract_subject)

    def test_create_requires_a_non_empty_project_name(self):
        with self.assertRaises(ValidationError):
            ProjectCreate(name="   ")

    def test_create_rejects_unknown_input_fields(self):
        with self.assertRaises(ValidationError):
            ProjectCreate.model_validate({"name": "Teszt projekt", "project_id": 7})

    def test_create_rejects_a_negative_contract_value(self):
        with self.assertRaises(ValidationError):
            ProjectCreate(name="Teszt projekt", contract_value=-1)

    async def test_create_rejects_an_empty_rpc_response(self):
        class Gateway:
            async def rpc(self, *_args, **_kwargs):
                return []

        with self.assertRaises(UpstreamError):
            await create_project(
                ProjectCreate(name="Teszt projekt"),
                "jwt",
                None,
                object(),
                Gateway(),
            )

    async def test_created_project_is_listed_and_can_be_opened(self):
        class Result:
            def __init__(self, data):
                self.data = data

        class Gateway:
            def __init__(self):
                self.projects: list[dict] = []

            async def rpc(self, function_name, _token, arguments):
                if function_name != "create_project":
                    raise AssertionError(f"Varatlan RPC: {function_name}")
                project = {"id": 17, **arguments["payload"], "is_deleted": False}
                self.projects.append(project)
                return [project]

            async def select(self, table, _token, **kwargs):
                if table != "projects":
                    raise AssertionError(f"Varatlan tabla: {table}")
                if kwargs.get("limit") == 1:
                    return Result([self.projects[0]])
                return Result(self.projects)

        gateway = Gateway()
        created = await create_project(
            ProjectCreate(name="Teszt projekt", work_number="T-17"),
            "jwt",
            None,
            object(),
            gateway,
        )
        projects = await list_projects("jwt", object(), gateway, search="")
        opened = await get_project(created["id"], "jwt", object(), gateway)

        self.assertEqual([project["id"] for project in projects], [created["id"]])
        self.assertEqual(opened["id"], created["id"])
        self.assertEqual(opened["work_number"], "T-17")

    def test_project_creation_migration_initializes_membership_after_idempotency_resolution(self):
        migration = Path(__file__).resolve().parents[2] / "adatbazis" / "013_megbizhato_projektletrehozas.sql"
        source = migration.read_text(encoding="utf-8")

        membership_position = source.index("insert into public.project_memberships")
        return_position = source.rindex("return result;")
        self.assertLess(membership_position, return_position)
        self.assertIn("on conflict (profile_id, project_id) do nothing", source)
        self.assertNotIn("digest(", source)

    def test_clean_install_uses_the_same_safe_project_creation_rules(self):
        installer = Path(__file__).resolve().parents[2] / "adatbazis" / "000_tiszta_telepites.sql"
        source = installer.read_text(encoding="utf-8")
        function_start = source.rfind("create or replace function public.create_project")
        function_end = source.find("$$;", function_start) + len("$$;")
        latest_function = source[function_start:function_end]

        self.assertIn("A projekt neve kotelezo.", latest_function)
        self.assertIn("insert into public.project_memberships", latest_function)
        self.assertIn("on conflict (profile_id, project_id) do nothing", latest_function)
        self.assertNotIn("digest(", latest_function)


if __name__ == "__main__":
    unittest.main()
