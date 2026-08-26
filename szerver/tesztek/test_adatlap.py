from __future__ import annotations

import unittest
from pathlib import Path

from alkalmazas.adatmodellek.beallitasok import ProjectDataSheetMetadata
from alkalmazas.adatmodellek.projektek import ProjectCreate, ProjectUpdate
from alkalmazas.vegpontok.beallitasok import router, save_project_profile


ROOT = Path(__file__).resolve().parents[1]


class ProfileGateway:
    def __init__(self) -> None:
        self.saved_rows: list[dict] = []
        self.on_conflict = ""

    async def rpc(self, name, token, payload):
        self.last_access_check = (name, token, payload)
        return True

    async def upsert(self, table, token, rows, *, on_conflict=None):
        self.saved_rows = rows
        self.on_conflict = on_conflict or ""
        self.saved_table = table
        return rows


class ProjectDataSheetModelTests(unittest.TestCase):
    def test_responsible_company_is_normalized(self):
        self.assertEqual(ProjectCreate(name="Teszt", responsible_company=" Minta Cég ").responsible_company, "Minta Cég")
        self.assertEqual(ProjectUpdate(responsible_company=" Minta Iroda ").responsible_company, "Minta Iroda")

    def test_profile_defaults_keep_old_projects_loadable(self):
        profile = ProjectDataSheetMetadata()
        self.assertEqual(profile.project_scale, "")
        self.assertEqual(profile.project_source, "")
        self.assertFalse(profile.nationally_significant)

    def test_frontend_uses_structured_data_sheet_and_fixed_company_select(self):
        script = (ROOT / "alkalmazas" / "statikus" / "alkalmazas.js").read_text(encoding="utf-8")
        style = (ROOT / "alkalmazas" / "statikus" / "megjelenes.css").read_text(encoding="utf-8")
        self.assertIn('const RESPONSIBLE_COMPANIES = ["Minta Cégcsoport Zrt.", "Minta Tervezőiroda Kft.", "Minta Partner Mérnökség"]', script)
        self.assertIn('<h2>Adatlap</h2>', script)
        self.assertIn('<h3>AZONOSÍTÓK</h3>', script)
        self.assertIn('<h3>PARTNEREK</h3>', script)
        self.assertIn('<h3>ALAPINFORMÁCIÓK</h3>', script)
        self.assertIn('name="responsible_company"', script)
        self.assertIn('<span>Megbízó</span><input name="main_customer"', script)
        self.assertNotIn('Közvetlen megrendelő', script)
        self.assertNotIn('Felelős cég / saját cég', script)
        self.assertIn("grid-template-columns: 280px minmax(0, 1fr)", style)
        self.assertIn("width: min(1260px, 100%)", style)


class ProjectDataSheetEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_project_profile_route_is_registered(self):
        self.assertIn(
            "/settings/{project_id}/project-profile",
            {route.path for route in router.routes},
        )

    async def test_profile_is_saved_to_existing_project_metadata(self):
        gateway = ProfileGateway()
        result = await save_project_profile(
            17,
            ProjectDataSheetMetadata(
                directorate="Közlekedési igazgatóság",
                project_role="Tervező",
                business_agreement="Keretszerződés szerint.",
                project_scale="Nagy",
                project_source="Európai uniós forrás",
                nationally_significant=True,
            ),
            "jwt",
            None,
            object(),
            gateway,
        )

        self.assertEqual(gateway.saved_table, "contract_metadata")
        self.assertEqual(gateway.on_conflict, "project_id,metadata_key")
        self.assertEqual({row["metadata_key"] for row in gateway.saved_rows}, {
            "directorate",
            "project_role",
            "business_agreement",
            "project_scale",
            "project_source",
            "nationally_significant",
        })
        self.assertTrue(result["nationally_significant"])
        self.assertEqual(result["project_source"], "Európai uniós forrás")


if __name__ == "__main__":
    unittest.main()
