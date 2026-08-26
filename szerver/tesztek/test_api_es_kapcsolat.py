from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest

import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError

from alkalmazas.adatmodellek.projektek import ProjectCreate, ProjectUpdate
from alkalmazas.adatmodellek.alvallalkozok import ContractStageCreate
from alkalmazas.adatmodellek.dokumentumok import OfferRequestDocumentWrite
from alkalmazas.beallitasok import Settings
from alkalmazas.vegpontok.projektek import archive_project, create_project, update_project
from alkalmazas.vegpontok.alvallalkozok import (
    _folder_position,
    _offer_request_defaults,
    _offer_request_document_for_export,
    _optional_table_rows,
    _strict_matrix_columns,
    _sync_single_part_bases,
    create_offer_request_document,
    update_offer_request_document,
)
from alkalmazas.vegpontok.penzugy import _validate_finance_mapping, _validate_unique_payment_reference
from alkalmazas.vegpontok.utemterv import _sync_project_contract_value
from alkalmazas.hibak import AuthorizationError, ConflictError, NotFoundError
from alkalmazas.adatmodellek.hitelesites import PasswordChangeRequest
from alkalmazas.webszerver import create_app
from alkalmazas.sebessegkorlat import SensitiveRateLimitMiddleware
from alkalmazas.supabase_kapcsolat import SupabaseGateway
from alkalmazas.teljesitmeny import (
    begin_request_metrics,
    current_request_metrics,
    end_request_metrics,
)


class ApiContractTests(unittest.TestCase):
    def test_openapi_contains_all_business_areas_without_environment_access(self):
        settings = Settings("https://example.supabase.co", "public-test-key")
        gateway = SupabaseGateway(settings, httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[]))))
        app = create_app(settings, gateway)
        paths = app.openapi()["paths"]
        expected = {
            "/api/projects", "/api/projects/{project_id}", "/api/disciplines/{project_id}/daily-progress",
            "/api/disciplines/{project_id}/daily-progress/{row_id}",
            "/api/disciplines/{project_id}/phases", "/api/disciplines/{project_id}/daily-rates",
            "/api/schedules/{project_id}/calculate", "/api/subcontractors/{project_id}/matrix",
            "/api/schedules/{project_id}/settings",
            "/api/schedules/{project_id}/timeline",
            "/api/schedules/{project_id}/export.xlsx",
            "/api/schedules/{project_id}/rows",
            "/api/schedules/{project_id}/rows/reorder",
            "/api/schedules/{project_id}/rows/{row_id}",
            "/api/schedules/{project_id}/contract-sections",
            "/api/schedules/{project_id}/contract-sections/{section_id}",
            "/api/schedules/{project_id}/milestones",
            "/api/schedules/{project_id}/milestones/{milestone_id}",
            "/api/subcontractors/{project_id}/matrix/{cell_id}",
            "/api/subcontractors/{project_id}/catalog",
            "/api/subcontractors/{project_id}/workspace",
            "/api/subcontractors/{project_id}/folders",
            "/api/subcontractors/{project_id}/folders/{folder_id}",
            "/api/subcontractors/{project_id}/folder-order",
            "/api/subcontractors/{project_id}/export.xlsx",
            "/api/subcontractors/{project_id}/workflows/{workflow_id}/documents",
            "/api/subcontractors/{project_id}/workflows/{workflow_id}/documents/offer-request",
            "/api/subcontractors/{project_id}/workflows/{workflow_id}/documents/{document_id}/preview",
            "/api/subcontractors/{project_id}/workflows/{workflow_id}/documents/{document_id}/export",
            "/api/subcontractors/{project_id}/workflows/{workflow_id}/documents/{document_id}/pdf",
            "/api/finance/{project_id}/export.xlsx",
            "/api/finance/{project_id}/mappings/{workflow_id}",
            "/api/subcontractors/{project_id}/workflows/{workflow_id}/step",
            "/api/subcontractors/{project_id}/matrix/base-values",
            "/api/subcontractors/{project_id}/matrix/stages",
            "/api/finance/{project_id}/summary", "/api/engagements/assignments",
            "/api/engagements/import/preview", "/api/notifications", "/api/admin/profiles",
            "/api/notifications/action", "/api/notifications/tasks/today",
            "/api/notifications/tasks", "/api/notifications/tasks/{task_id}",
            "/api/notifications/{alert_key}/read",
            "/api/engagements/attachments/{attachment_id}/download",
            "/api/admin/application-clock",
            "/api/settings/{project_id}",
            "/api/settings/{project_id}/daily-rates",
            "/api/settings/{project_id}/phases",
            "/api/settings/{project_id}/disciplines/{discipline_id}",
            "/api/settings/{project_id}/offer-request",
            "/api/settings/{project_id}/company-contacts",
            "/api/settings/{project_id}/company-contacts/{contact_id}",
            "/api/settings/schedule-keys",
            "/api/settings/schedule-keys/{key_id}",
            "/api/settings/calendar-exceptions",
            "/api/finance/company-cash-flow",
            "/api/finance/company-cash-flow/export",
            "/api/finance/{project_id}/payments/{payment_id}",
            "/api/auth/change-password",
        }
        self.assertTrue(expected.issubset(paths))
        self.assertTrue({"get", "post"}.issubset(paths["/api/projects"]))
        self.assertTrue({"get", "patch", "delete"}.issubset(paths["/api/projects/{project_id}"]))
        self.assertTrue({"put", "delete"}.issubset(paths["/api/finance/{project_id}/payments/{payment_id}"]))
        pdf_parameters = paths[
            "/api/subcontractors/{project_id}/workflows/{workflow_id}/documents/{document_id}/pdf"
        ]["get"]["parameters"]
        self.assertTrue(
            any(parameter["name"] == "preview" and not parameter["required"] for parameter in pdf_parameters)
        )
        export_parameters = paths[
            "/api/subcontractors/{project_id}/workflows/{workflow_id}/documents/{document_id}/export"
        ]["get"]["parameters"]
        format_parameter = next(parameter for parameter in export_parameters if parameter["name"] == "format")
        self.assertFalse(format_parameter["required"])
        self.assertEqual(format_parameter["schema"]["enum"], ["pdf", "word"])

    def test_document_export_stops_before_rls_read_without_project_access(self):
        class DeniedGateway:
            async def rpc(self, name, token, payload):
                self.rpc_call = (name, token, payload)
                return False

            async def select(self, *_args, **_kwargs):
                raise AssertionError("Tiltott projekt esetén nem indulhat dokumentumlekérés.")

        gateway = DeniedGateway()
        with self.assertRaises(AuthorizationError) as context:
            asyncio.run(_offer_request_document_for_export(11, 22, 33, "jwt-token", gateway))
        self.assertEqual(context.exception.status_code, 403)
        self.assertEqual(
            gateway.rpc_call,
            ("can_access_project", "jwt-token", {"target_project_id": 11, "write_access": False}),
        )

    def test_document_export_accepts_legacy_json_text_snapshot(self):
        class Gateway:
            async def rpc(self, *_args, **_kwargs):
                return True

            async def select(self, table, _token, **_kwargs):
                rows = {
                    "subcontractor_workflows": [{"id": 22, "project_id": 11}],
                    "workflow_documents": [{
                        "id": 33,
                        "project_id": 11,
                        "workflow_id": 22,
                        "document_type": "offer_request",
                        "data": '{"title":"Árajánlatkérő","project_name":"Minta"}',
                    }],
                }[table]
                return SimpleNamespace(data=rows)

        document = asyncio.run(
            _offer_request_document_for_export(11, 22, 33, "jwt-token", Gateway())
        )
        self.assertEqual(document["data"]["project_name"], "Minta")

    def test_offer_request_update_recovers_empty_patch_representation(self):
        class Gateway:
            def __init__(self):
                self.document_reads = 0

            async def select(self, table, _token, **_kwargs):
                if table == "subcontractor_workflows":
                    rows = [{"id": 22, "project_id": 11, "company_name": "Minta Kft.", "discipline": "Út"}]
                elif table == "workflow_documents":
                    self.document_reads += 1
                    rows = [{
                        "id": 33,
                        "project_id": 11,
                        "workflow_id": 22,
                        "document_type": "offer_request",
                        "status": "draft",
                        "revision_no": 1,
                        "title": "Árajánlatkérő",
                        "data": {"request_text": "Mentett szöveg"},
                    }]
                elif table == "projects":
                    rows = [{"id": 11, "name": "Minta projekt", "work_number": "M-11"}]
                elif table in {"project_milestones", "project_contract_sections", "project_offer_request_settings"}:
                    rows = []
                else:
                    raise AssertionError(table)
                return SimpleNamespace(data=rows)

            async def update(self, *_args, **_kwargs):
                return []

        payload = OfferRequestDocumentWrite.model_validate({
            "title": "Árajánlatkérő",
            "data": {"request_text": "Mentett szöveg"},
        })
        gateway = Gateway()
        result = asyncio.run(
            update_offer_request_document(11, 22, 33, payload, "jwt-token", None, gateway=gateway)
        )
        self.assertEqual(result["id"], 33)
        self.assertEqual(gateway.document_reads, 2)

    def test_offer_request_draft_can_be_created_for_a_later_workflow_step(self):
        class Gateway:
            def __init__(self):
                self.inserted = None

            async def select(self, table, _token, **_kwargs):
                rows = {
                    "subcontractor_workflows": [{
                        "id": 22,
                        "project_id": 11,
                        "current_step": 6,
                        "company_name": "Minta Kft.",
                        "discipline": "Környezetvédelem",
                        "status_note": "",
                    }],
                    "workflow_documents": [],
                    "projects": [{"id": 11, "name": "Minta projekt", "work_number": "M-11"}],
                    "project_milestones": [],
                    "project_contract_sections": [],
                    "project_offer_request_settings": [{
                        "history": "Projektelőzmény",
                        "task_description": "Tervezési feladat",
                    }],
                }[table]
                return SimpleNamespace(data=rows)

            async def insert(self, table, _token, data):
                self.inserted = (table, data)
                return [{"id": 101, **data, "status": "draft"}]

        gateway = Gateway()
        payload = OfferRequestDocumentWrite.model_validate({
            "title": "Árajánlatkérő",
            "data": {
                "history": "Projektelőzmény",
                "task_description": "Tervezési feladat",
                "contacts": "Teszt Elek | teszt@example.hu",
            },
        })
        created = asyncio.run(
            create_offer_request_document(11, 22, payload, "jwt-token", None, gateway=gateway)
        )
        self.assertEqual(created["status"], "draft")
        self.assertEqual(gateway.inserted[0], "workflow_documents")
        self.assertEqual(gateway.inserted[1]["workflow_id"], 22)
        self.assertEqual(gateway.inserted[1]["data"]["history"], "Projektelőzmény")

    def test_offer_request_defaults_survive_pending_optional_settings_migration(self):
        class Gateway:
            async def select(self, table, _token, **_kwargs):
                if table in {"project_offer_request_settings", "project_company_contacts"}:
                    raise NotFoundError("A kért rekord nem található.")
                rows = {
                    "projects": [{"id": 11, "name": "Minta projekt", "work_number": "M-11"}],
                    "project_milestones": [],
                    "project_contract_sections": [],
                }[table]
                return SimpleNamespace(data=rows)

        gateway = Gateway()
        workflow = {
            "id": 22,
            "project_id": 11,
            "company_name": "Minta Kft.",
            "discipline": "Környezetvédelem",
            "status_note": "Folyamatmegjegyzés",
        }
        defaults = asyncio.run(_offer_request_defaults(11, workflow, "jwt-token", gateway))
        contacts = asyncio.run(
            _optional_table_rows(
                gateway,
                "project_company_contacts",
                "jwt-token",
                filters={"project_id": "eq.11"},
            )
        )
        self.assertEqual(defaults["project_name"], "Minta projekt")
        self.assertEqual(defaults["history"], "")
        self.assertEqual(defaults["task_description"], "Folyamatmegjegyzés")
        self.assertEqual(contacts, [])

    def test_sensitive_routes_have_rate_limits(self):
        self.assertEqual(SensitiveRateLimitMiddleware._limit_for("POST", "/api/auth/login"), ("/api/auth/login", 10, 60))
        self.assertEqual(
            SensitiveRateLimitMiddleware._limit_for("POST", "/api/auth/change-password"),
            ("/api/auth/change-password", 5, 900),
        )
        self.assertIsNotNone(
            SensitiveRateLimitMiddleware._limit_for("POST", "/api/engagements/import/preview")
        )

    def test_hungarian_application_shell_and_renamed_assets_are_served(self):
        settings = Settings("https://example.supabase.co", "public-test-key")
        gateway = SupabaseGateway(
            settings,
            httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[]))),
        )
        app = create_app(settings, gateway)
        with TestClient(app) as client:
            page = client.get("/")
            self.assertEqual(page.status_code, 200)
            self.assertIn("app;dur=", page.headers["server-timing"])
            self.assertIn("supabase;dur=", page.headers["server-timing"])
            self.assertEqual(page.headers["x-supabase-request-count"], "0")
            policy = page.headers["content-security-policy"]
            self.assertIn("script-src 'self'", policy)
            self.assertNotIn("script-src 'self' 'unsafe-inline'", policy)
            self.assertIn("style-src-attr 'unsafe-inline'", policy)
            self.assertIn("Bejelentkezés", page.text)
            self.assertIn('data-module="schedule"><span aria-hidden="true">▤</span> Ütemterv</button>', page.text)
            self.assertIn('data-module="settings"><span aria-hidden="true">⚙</span> Adatok</button>', page.text)
            self.assertNotIn('data-module="overview"', page.text)
            self.assertNotIn("Ütemterv / Tervezési díj", page.text)
            self.assertIn("/static/alkalmazas.js", page.text)
            client_styles = client.get("/static/megjelenes.css")
            self.assertEqual(client_styles.status_code, 200)
            client_script = client.get("/static/alkalmazas.js")
            self.assertEqual(client_script.status_code, 200)
            self.assertIn("const form = event.currentTarget", client_script.text)
            self.assertIn("setProjectGate(false)", client_script.text)
            self.assertIn('row.addEventListener("dblclick"', client_script.text)
            self.assertIn("data-discipline-name", client_script.text)
            self.assertIn('hasPermission("project_create")', client_script.text)
            self.assertIn("Új projekt", client_script.text)
            self.assertIn("Projekt szerkesztése", client_script.text)
            self.assertIn("const idempotencyKey = crypto.randomUUID()", client_script.text)
            self.assertIn("idempotency_key: idempotencyKey", client_script.text)
            self.assertIn("if (submitting) return", client_script.text)
            self.assertIn('form.setAttribute("aria-busy", "true")', client_script.text)
            self.assertIn("if (form.isConnected) closeModal()", client_script.text)
            self.assertIn('submitButton.textContent = "Projekt létrehozása…"', client_script.text)
            self.assertIn('id="project-create-error"', client_script.text)
            self.assertIn('name="contract_subject"', client_script.text)
            self.assertIn("project.contract_subject", client_script.text)
            self.assertIn("const project = await api(`/projects/${selectedProject.id}`)", client_script.text)
            self.assertIn("state.selectedProjectId !== selectedProject.id", client_script.text)
            self.assertIn("function renderProjectContractBase()", client_script.text)
            self.assertIn('schedule: ["Ütemterv", "Tervezési és pénzügyi mérföldkövek"]', client_script.text)
            self.assertIn('settings: ["Adatok", "Adatlap és projektstruktúra"]', client_script.text)
            self.assertIn('module = module === "overview" ? "settings" : module;', client_script.text)
            self.assertIn('state.settingsView = "project";', client_script.text)
            self.assertIn('await selectModule("settings");', client_script.text)
            self.assertNotIn("Ütemterv / Tervezési díj", client_script.text)
            self.assertIn("function compareScheduleRows", client_script.text)
            self.assertNotIn('data-field="position"', client_script.text)
            self.assertNotIn('name="position" type="number" min="1" step="1"', client_script.text)
            self.assertNotIn('data-move="up"', client_script.text)
            self.assertNotIn('data-move="down"', client_script.text)
            self.assertIn('position: Number(currentRow?.position || 0)', client_script.text)
            self.assertIn('name="section_no"', client_script.text)
            self.assertIn('name="phase_no"', client_script.text)
            self.assertIn("[0, 1, 2, 3, 4, 5]", client_script.text)
            self.assertIn("const nextNo = [1, 2, 3, 4, 5].find", client_script.text)
            self.assertIn("!usedNumbers.has(number)) ?? 0", client_script.text)
            self.assertIn('name="short_name"', client_script.text)
            self.assertIn('name="official_name"', client_script.text)
            self.assertIn('name="description" rows="8" maxlength="5000"', client_script.text)
            self.assertIn('name="schedule_row_id"', client_script.text)
            self.assertIn("name: data.official_name", client_script.text)
            self.assertIn("schedule_row_id: scheduleLinked", client_script.text)
            self.assertIn("Eltolás a hivatkozott ütemtervsor befejezésétől (naptári nap)", client_script.text)
            self.assertIn("Eltolás a hivatkozott mérföldkő dátumától (naptári nap)", client_script.text)
            self.assertIn('data-contract-section-id="${item.id}"', client_script.text)
            self.assertIn('data-milestone-id="${item.id}"', client_script.text)
            self.assertIn("/contract-sections/${section.id}", client_script.text)
            self.assertIn("/milestones/${milestone.id}", client_script.text)
            self.assertIn(".milestone-group.section-color-0", client_styles.text)
            self.assertIn("Vállalkozó", client_script.text)
            self.assertIn("Megbízó", client_script.text)
            self.assertIn("Saját státusz", client_script.text)
            self.assertNotIn("schedule-project-form", client_script.text)
            self.assertIn('id="edit-project"', client_script.text)
            self.assertIn('id="rename-project"', client_script.text)
            self.assertIn('aria-pressed="false"', client_script.text)
            self.assertIn('row.setAttribute("aria-pressed", String(isSelected))', client_script.text)
            self.assertIn("button.disabled = !project", client_script.text)
            self.assertIn('addEventListener("click", openSelectedProject)', client_script.text)
            self.assertIn('.project-row[aria-pressed="true"]', client_styles.text)
            self.assertIn("Projekt átnevezése", client_script.text)
            self.assertIn("renderSettings", client_script.text)
            self.assertIn("Szakágak és projektfázisok", client_script.text)
            self.assertIn('data-settings-view="milestones"', client_script.text)
            self.assertIn('data-settings-view="schedule_keys"', client_script.text)
            self.assertIn('state.scheduleView === "milestones"', client_script.text)
            self.assertIn('state.settingsView = "milestones"', client_script.text)
            self.assertIn("schedule_keys_available", client_script.text)
            self.assertIn('data-settings-view="schedule_keys"', client_script.text)
            self.assertIn('id="schedule-financial-phase"', client_script.text)
            self.assertIn("Összesített Gantt", client_script.text)
            self.assertIn("financial_phase_no", client_script.text)
            self.assertIn("function referenceOptions", client_script.text)
            self.assertIn("schedule_rows_financial_phase_review", (Path(__file__).resolve().parents[2] / "adatbazis" / "014_utemterv_jelkulcsok_es_kapcsolatok.sql").read_text(encoding="utf-8"))
            self.assertIn("Céges árbevétel és cash-flow", client_script.text)
            self.assertIn("/auth/change-password", client_script.text)
            self.assertIn("Fiók és jelszó", client_script.text)
            self.assertIn("/subcontractors/${state.project.id}/workspace", client_script.text)
            self.assertIn("offer-request-document-form", client_script.text)
            self.assertIn("Ajánlatkérő összeállítása", client_script.text)
            self.assertIn("workflow-panel-resizer", client_script.text)
            self.assertIn("offer-request-settings-form", client_script.text)
            self.assertIn("offer-request-contact-select", client_script.text)
            self.assertIn("Előkép", client_script.text)
            self.assertIn("Exportálás", client_script.text)
            self.assertIn("offer-request-export-format", client_script.text)
            self.assertIn("Ajánlatkérő kiadása", client_script.text)
            self.assertIn("Új változat készítése", client_script.text)
            self.assertIn("Nincs hozzáférés a dokumentumtárhoz.", client_script.text)
            self.assertIn("A dokumentum API vagy a keresett dokumentum nem található.", client_script.text)
            self.assertIn("A dokumentumtár kiszolgálása hibát jelzett.", client_script.text)
            self.assertIn("Munkaszám", client_script.text)
            self.assertIn("Vállalkozó", client_script.text)
            self.assertIn("finance-cost-row", client_script.text)
            self.assertIn("console.time(", client_script.text)
            self.assertNotIn("Dátum nélküli oszlopok", client_script.text)
            self.assertNotIn('option value="Késik"', client_script.text)
            self.assertIn("Partner szerepe", client_script.text)
            self.assertIn("Kifizetési szakaszok száma", client_script.text)
            self.assertNotIn("<th>Lépés</th>", client_script.text)
            self.assertNotIn("Pénzügyi osztály", client_script.text)
            self.assertIn(">Törlés</button>", client_script.text)
            self.assertTrue(client_script.text.rstrip().endswith("showLoginView();"))
            self.assertNotIn("event.currentTarget.reset()", client_script.text)


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_identity_checks_share_one_supabase_round_trip_pair(self):
        requests: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request.url.path)
            await asyncio.sleep(0.01)
            if request.url.path == "/auth/v1/user":
                return httpx.Response(200, json={"id": "user-1", "email": "user@example.com"})
            if request.url.path == "/rest/v1/profiles":
                return httpx.Response(200, json=[{"id": "user-1", "role": "editor"}])
            return httpx.Response(404)

        settings = Settings("https://example.supabase.co", "public-anon-key")
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway = SupabaseGateway(settings, client)
        first, second = await asyncio.gather(
            gateway.authenticated_identity("same-user-jwt"),
            gateway.authenticated_identity("same-user-jwt"),
        )
        self.assertEqual(first, second)
        self.assertEqual(requests.count("/auth/v1/user"), 1)
        self.assertEqual(requests.count("/rest/v1/profiles"), 1)
        await client.aclose()

    async def test_folder_positions_are_one_based_and_clamped(self):
        self.assertEqual(_folder_position(1, 4), 0)
        self.assertEqual(_folder_position(3, 4), 2)
        self.assertEqual(_folder_position(99, 4), 4)
        self.assertEqual(_folder_position(0, 4), 4)

    async def test_user_token_is_forwarded_for_rls(self):
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["authorization"] = request.headers["authorization"]
            captured["apikey"] = request.headers["apikey"]
            return httpx.Response(200, json=[{"id": 1}])

        settings = Settings("https://example.supabase.co", "public-anon-key")
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway = SupabaseGateway(settings, client)
        result = await gateway.select("projects", "user-jwt")
        self.assertEqual(result.data, [{"id": 1}])
        self.assertEqual(captured["authorization"], "Bearer user-jwt")
        self.assertEqual(captured["apikey"], "public-anon-key")
        await client.aclose()

    async def test_supabase_not_found_preserves_postgrest_error_code(self):
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                404,
                json={
                    "code": "PGRST205",
                    "message": "Could not find the table 'public.schedule_keys' in the schema cache",
                },
            )

        settings = Settings("https://example.supabase.co", "public-anon-key")
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway = SupabaseGateway(settings, client)
        with self.assertRaises(NotFoundError) as context:
            await gateway.select("schedule_keys", "user-jwt")
        self.assertEqual(context.exception.detail["code"], "PGRST205")
        await client.aclose()

    async def test_supabase_round_trips_are_counted_without_logging_credentials(self):
        settings = Settings("https://example.supabase.co", "public-anon-key")
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[{"id": 1}]))
        )
        gateway = SupabaseGateway(settings, client)
        token = begin_request_metrics()
        try:
            await gateway.select("projects", "secret-user-jwt")
            metrics = current_request_metrics()
        finally:
            end_request_metrics(token)
            await client.aclose()
        self.assertEqual(metrics["supabase_count"], 1)
        self.assertEqual(metrics["supabase_paths"], {"/rest/v1/projects": 1})

    async def test_password_update_uses_authenticated_supabase_user_endpoint(self):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["authorization"] = request.headers["authorization"]
            captured["body"] = request.read().decode("utf-8")
            return httpx.Response(200, json={"id": "user-1"})

        settings = Settings("https://example.supabase.co", "public-anon-key")
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway = SupabaseGateway(settings, client)
        await gateway.update_password("verified-user-jwt", "regi-jelszo", "uj-jelszo-1234")
        self.assertEqual(captured["method"], "PUT")
        self.assertEqual(captured["authorization"], "Bearer verified-user-jwt")
        self.assertIn('"current_password":"regi-jelszo"', captured["body"])
        self.assertIn('"password":"uj-jelszo-1234"', captured["body"])
        await client.aclose()

    async def test_password_change_model_rejects_mismatch_and_reuse(self):
        with self.assertRaises(ValueError):
            PasswordChangeRequest(
                current_password="regi-jelszo",
                new_password="hosszu-uj-jelszo-123",
                new_password_confirmation="masik-uj-jelszo-123",
            )
        with self.assertRaises(ValueError):
            PasswordChangeRequest(
                current_password="ugyanaz-a-jelszo-123",
                new_password="ugyanaz-a-jelszo-123",
                new_password_confirmation="ugyanaz-a-jelszo-123",
            )

    async def test_contract_base_sync_stops_before_writing_paid_matrix_changes(self):
        class Result:
            def __init__(self, data):
                self.data = data

        class Gateway:
            def __init__(self):
                self.writes = []

            async def select(self, table, token, **kwargs):
                if table == "contract_matrix":
                    return Result([{"id": 5, "reference_id": "ALV_7_SZ1_MD", "column_code": "M_12", "percent": 50, "amount": 100}])
                if table == "payments":
                    return Result([{"id": 9, "reference": "KIA_WF_7_COL_M_12", "status": "Pénzügyileg teljesítve", "amount": 100}])
                return Result([])

            async def upsert(self, *args, **kwargs):
                self.writes.append(("upsert", args, kwargs))

            async def update(self, *args, **kwargs):
                self.writes.append(("update", args, kwargs))

        gateway = Gateway()
        workflow = {
            "id": 7,
            "part_count": 1,
            "acceptance": "Elfogadva",
            "current_step": 5,
            "contract_fee": "400",
            "copyright_fee": "0",
        }
        with self.assertRaises(ConflictError):
            await _sync_single_part_bases(1, workflow, "jwt", gateway)
        self.assertEqual(gateway.writes, [])

    async def test_matrix_columns_use_one_strict_chronological_sequence(self):
        columns, warnings = _strict_matrix_columns(
            milestones=[
                {"id": 2, "name": "Februári mérföldkő", "planned_date": "2026-02-03", "phase_no": 2},
                {"id": 1, "name": "Januári mérföldkő", "planned_date": "2026-01-20", "phase_no": 1},
            ],
            stages=[
                {"id": 9, "name": "Januári hóközi", "stage_date": "2026-01-25"},
            ],
            cells=[],
            fallback_date="2026-01-01",
        )
        self.assertEqual(
            [column["code"] for column in columns],
            ["M_1", "STAGE_9", "M_2"],
        )
        self.assertEqual(warnings, [])

    async def test_legacy_matrix_column_gets_dated_fallback_and_warning(self):
        columns, warnings = _strict_matrix_columns(
            milestones=[],
            stages=[],
            cells=[{"column_code": "EMP_2026.01.hónap"}],
            fallback_date="2026-01-01",
        )
        self.assertEqual(columns[0]["stage_date"], "2026-01-01")
        self.assertTrue(columns[0]["used_fallback_date"])
        self.assertEqual(len(warnings), 1)

    async def test_contract_stage_requires_a_date(self):
        with self.assertRaises(ValidationError):
            ContractStageCreate(name="Hóközi ütem")


class FinanceEndpointValidationTests(unittest.IsolatedAsyncioTestCase):
    class Result:
        def __init__(self, data):
            self.data = data

    async def test_duplicate_finance_reference_is_rejected(self):
        class Gateway:
            async def select(self, table, token, **kwargs):
                return FinanceEndpointValidationTests.Result([{"id": 17, "reference": "BEV_MS_3"}])

        with self.assertRaises(ConflictError):
            await _validate_unique_payment_reference(1, {"reference": "BEV_MS_3"}, "jwt", Gateway())

    async def test_mapping_must_use_workflow_and_discipline_from_same_project(self):
        class Gateway:
            async def select(self, table, token, **kwargs):
                if table == "subcontractor_workflows":
                    return FinanceEndpointValidationTests.Result([{"id": 8, "project_id": 1}])
                return FinanceEndpointValidationTests.Result([{"name": "A-Útépítés"}])

        with self.assertRaises(ConflictError):
            await _validate_finance_mapping(
                1,
                {"workflow_id": 8, "discipline_name": "Másik projekt szakága"},
                "jwt",
                Gateway(),
            )


class ProjectCrudTests(unittest.IsolatedAsyncioTestCase):
    class Gateway:
        def __init__(self):
            self.calls: list[tuple[str, dict]] = []

        async def rpc(self, function_name: str, access_token: str, payload: dict):
            self.calls.append((function_name, payload))
            if function_name == "archive_project":
                return None
            project_id = payload.get("target_project_id", 91)
            data = payload.get("payload", {})
            return [{"id": project_id, "name": data.get("name", "Teszt projekt"), "status": data.get("status", "Aktív")}]

        async def select(self, table: str, access_token: str, **kwargs):
            class Result:
                data = [{"id": 4, "project_id": 91}]
            return Result()

    async def test_create_update_and_delete_use_the_guarded_project_rpcs(self):
        gateway = self.Gateway()
        created = await create_project(ProjectCreate(name="Teszt projekt"), "jwt", None, object(), gateway)
        updated = await update_project(91, ProjectUpdate(name="Átnevezett projekt"), "jwt", None, object(), gateway)
        deleted = await archive_project(91, "jwt", None, object(), gateway)

        self.assertEqual(created["id"], 91)
        self.assertEqual(updated["name"], "Átnevezett projekt")
        self.assertEqual(deleted, {"archived": True})
        self.assertEqual([name for name, _ in gateway.calls], ["create_project", "update_project", "archive_project"])
        self.assertEqual(gateway.calls[2][1], {"target_project_id": 91})

    async def test_contract_value_cannot_override_existing_contract_sections(self):
        gateway = self.Gateway()
        with self.assertRaises(ConflictError):
            await update_project(91, ProjectUpdate(contract_value=123), "jwt", None, object(), gateway)
        self.assertEqual(gateway.calls, [])

    async def test_contract_sections_sync_the_project_summary_value(self):
        class Result:
            def __init__(self, data):
                self.data = data

        class Gateway:
            def __init__(self):
                self.rpc_payload = None

            async def select(self, table, token, **kwargs):
                return Result([
                    {"original_fee": "100000000", "modified_fee": "120000000"},
                    {"original_fee": "200000000", "modified_fee": "0"},
                ])

            async def rpc(self, function_name, token, payload):
                self.rpc_payload = (function_name, payload)
                return []

        gateway = Gateway()
        total = await _sync_project_contract_value(91, "jwt", gateway)
        self.assertEqual(str(total), "320000000")
        self.assertEqual(gateway.rpc_payload, ("update_project", {"target_project_id": 91, "payload": {"contract_value": "320000000"}}))

    async def test_storage_download_url_is_short_lived_and_user_scoped(self):
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["authorization"] = request.headers["authorization"]
            return httpx.Response(200, json={"signedURL": "/object/sign/engagement-attachments/fajl?token=egyszeri"})

        settings = Settings("https://example.supabase.co", "public-anon-key")
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway = SupabaseGateway(settings, client)
        url = await gateway.signed_download_url("engagement-attachments", "assignments/1/fajl.pdf", "user-jwt")
        self.assertEqual(captured["authorization"], "Bearer user-jwt")
        self.assertTrue(url.startswith("https://example.supabase.co/storage/v1/object/sign/"))
        await client.aclose()


if __name__ == "__main__":
    unittest.main()
