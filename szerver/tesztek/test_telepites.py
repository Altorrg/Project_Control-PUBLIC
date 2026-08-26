from __future__ import annotations

from pathlib import Path
import unittest

from eszkozok.telepitesi_sql_osszeallitasa import SOURCE_FILES, build_installer


class InstallationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[2]
        cls.database_directory = cls.root / "adatbazis"
        cls.installer = build_installer(cls.database_directory)

    def test_installer_is_one_atomic_transaction(self) -> None:
        transaction_lines = [line.strip().lower() for line in self.installer.splitlines()]
        self.assertEqual(transaction_lines.count("begin;"), 1)
        self.assertEqual(transaction_lines.count("commit;"), 1)

    def test_installer_contains_every_clean_source(self) -> None:
        for file_name in SOURCE_FILES:
            self.assertIn(f"-- ===== {file_name} =====", self.installer)

    def test_installer_contains_no_historical_project_data(self) -> None:
        forbidden_fragments = (
            "legacy_source_rows(",
            "insert into public.projects values",
        )
        for fragment in forbidden_fragments:
            self.assertNotIn(fragment, self.installer)

    def test_repair_promotes_local_initial_admin(self) -> None:
        repair_sql = (self.database_directory / "004_rendszerellenorzes_es_javitas.sql").read_text(encoding="utf-8")
        self.assertIn("admin@demo.local", repair_sql)
        self.assertIn("admin@example.com", repair_sql)
        self.assertIn("then 'admin'", repair_sql)
        self.assertIn("on conflict (id) do update", repair_sql)

    def test_every_non_admin_profile_becomes_editor(self) -> None:
        security_sql = (self.database_directory / "002_biztonsag_es_logika.sql").read_text(encoding="utf-8")
        repair_sql = (self.database_directory / "004_rendszerellenorzes_es_javitas.sql").read_text(encoding="utf-8")
        self.assertIn("'editor'", security_sql)
        self.assertIn("when excluded.role = 'admin' then 'admin' else 'editor'", repair_sql)
        self.assertIn("delete from public.role_permissions where role <> 'editor'", repair_sql)
        self.assertIn("check (role in ('admin', 'editor'))", repair_sql)

    def test_all_active_editors_can_access_every_project(self) -> None:
        security_sql = (self.database_directory / "002_biztonsag_es_logika.sql").read_text(encoding="utf-8")
        function_sql = security_sql.split("create or replace function public.can_access_project", 1)[1].split("$$;", 1)[0]
        self.assertIn("profile.role in ('admin', 'editor')", function_sql)
        self.assertNotIn("project_memberships pm", function_sql)

        access_repair_sql = (
            self.database_directory / "005_globalis_szerkesztoi_hozzaferes.sql"
        ).read_text(encoding="utf-8")
        repair_function_sql = access_repair_sql.split(
            "create or replace function public.can_access_project", 1
        )[1].split("$$;", 1)[0]
        self.assertIn("profile.role in ('admin', 'editor')", repair_function_sql)
        self.assertNotIn("project_memberships pm", repair_function_sql)

    def test_access_repair_recreates_global_project_policy(self) -> None:
        access_repair_sql = (
            self.database_directory / "005_globalis_szerkesztoi_hozzaferes.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("create policy projects_read", access_repair_sql)
        self.assertIn("public.can_access_project(id, false)", access_repair_sql)
        self.assertIn("where role <> 'admin'", access_repair_sql)

    def test_repair_verifies_project_crud(self) -> None:
        repair_sql = (self.database_directory / "004_rendszerellenorzes_es_javitas.sql").read_text(encoding="utf-8")
        self.assertIn("public.create_project(jsonb)", repair_sql)
        self.assertIn("public.update_project(bigint,jsonb)", repair_sql)
        self.assertIn("public.archive_project(bigint)", repair_sql)

    def test_workflow_documents_are_versioned_and_project_protected(self) -> None:
        migration = (self.database_directory / "007_alvallalkozoi_dokumentumok.sql").read_text(encoding="utf-8")
        self.assertIn("unique(workflow_id, document_type, revision_no)", migration)
        self.assertIn("alter table public.workflow_documents enable row level security", migration)
        self.assertIn("public.can_access_project(project_id, true)", migration)
        self.assertIn("on table public.workflow_documents", migration)
        self.assertIn("to authenticated", migration)
        self.assertIn("pg_get_serial_sequence", migration)
        self.assertIn("revoke all", migration)

    def test_matrix_migration_dates_and_links_every_legacy_column(self) -> None:
        migration = (self.database_directory / "008_matrix_datumok.sql").read_text(encoding="utf-8")
        self.assertIn("between 1 and 12", migration)
        self.assertIn("column_code = 'STAGE_' || stages.id::text", migration)
        self.assertIn("alter column stage_date set not null", migration)
        self.assertIn("contract_stages_project_date_idx", migration)

    def test_project_metadata_and_offer_status_migration_is_idempotent(self) -> None:
        migration = (
            self.database_directory / "009_projekt_es_statusz_adatminoseg.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("add column if not exists work_number", migration)
        self.assertIn("add column if not exists responsible_company", migration)
        self.assertIn("set offer_status = 'Elutasítva'", migration)
        self.assertIn("offer_status in ('Kiküldésre vár', 'Kiküldve', 'Elutasítva')", migration)

    def test_schedule_key_master_data_migration_is_project_independent_and_audited(self) -> None:
        migration = (self.database_directory / "014_utemterv_jelkulcsok_es_kapcsolatok.sql").read_text(encoding="utf-8")
        self.assertIn("create table if not exists public.schedule_keys", migration)
        self.assertIn("code_key text generated always as (lower(btrim(code))) stored unique", migration)
        self.assertIn("alter table public.schedule_keys enable row level security", migration)
        self.assertIn("public.has_permission('master_data_admin')", migration)
        self.assertIn("create trigger audit_changes", migration)

    def test_schedule_financial_phase_migration_preserves_legacy_values(self) -> None:
        migration = (self.database_directory / "014_utemterv_jelkulcsok_es_kapcsolatok.sql").read_text(encoding="utf-8")
        self.assertIn("add column if not exists financial_phase_no integer", migration)
        self.assertIn("add column if not exists schedule_key_id bigint", migration)
        self.assertIn("schedule_rows_project_financial_phase_fkey", migration)
        self.assertIn("schedule_rows_financial_phase_review", migration)
        self.assertIn("single_phase_assignment", migration)
        self.assertIn("where row.financial_phase_no is null", migration)

    def test_subcontractor_schedule_key_and_actionable_gap_migration_is_guarded(self) -> None:
        migration = (self.database_directory / "014_utemterv_jelkulcsok_es_kapcsolatok.sql").read_text(encoding="utf-8")
        self.assertIn("create table if not exists public.subcontractor_workflow_schedule_keys", migration)
        self.assertIn("unique(workflow_id, financial_phase_no, schedule_key_id)", migration)
        self.assertIn("references public.project_contract_sections(project_id, section_no)", migration)
        self.assertIn("replace_subcontractor_workflow_schedule_keys", migration)
        self.assertIn("public.can_access_project(target_project_id, true)", migration)
        self.assertIn("subcontractor_workflow_schedule_key_review", migration)
        self.assertIn("current_actionable_gaps", migration)
        self.assertIn("public.current_notifications()", migration)

    def test_notification_tasks_migration_is_private_and_idempotent(self) -> None:
        migration = (self.database_directory / "016_ertesitesek_es_mai_teendok.sql").read_text(encoding="utf-8")
        self.assertIn("create table if not exists public.notification_tasks", migration)
        self.assertIn("alter table public.notification_tasks enable row level security", migration)
        self.assertIn("profile_id = auth.uid()", migration)
        self.assertIn("public.can_access_project(project_id, false)", migration)
        self.assertIn("create or replace function public.notification_action", migration)
        self.assertIn("interval '15 minutes'", migration)
        self.assertIn("interval '24 hours'", migration)
        self.assertIn("date_trunc('month', value)", migration)
        self.assertIn("select public.app_today() value", migration)
        self.assertIn("from public.daily_progress progress", migration)
        self.assertIn("'disciplines' target_module", migration)
        self.assertIn("project_quality as", migration)
        self.assertIn("group by p.id, p.name, m.value", migration)

    def test_personal_admin_clock_migration_does_not_use_global_clock_keys(self) -> None:
        migration = (self.database_directory / "017_szemelyes_tesztido.sql").read_text(encoding="utf-8")
        self.assertIn("'time_offset_days:' || current_profile_id::text", migration)
        self.assertIn("profile.role = 'admin'", migration)
        self.assertIn("return current_date", migration)

    def test_weekly_task_recheck_only_tracks_system_notifications(self) -> None:
        migration = (self.database_directory / "018_heti_feladat_ujraellenorzes.sql").read_text(encoding="utf-8")
        self.assertIn("add column if not exists source_alert_key", migration)
        self.assertIn("public.weekly_completed_task_notifications()", migration)
        self.assertIn("task.source_alert_key is not null", migration)
        self.assertIn("extract(isodow from today.value) = 5", migration)
        self.assertIn("time '09:00'", migration)
        self.assertIn("at time zone 'Europe/Budapest'", migration)

    def test_notification_frontend_exposes_today_tasks_and_explicit_actions(self) -> None:
        static_directory = self.root / "szerver" / "alkalmazas" / "statikus"
        javascript = (static_directory / "alkalmazas.js").read_text(encoding="utf-8")
        stylesheet = (static_directory / "megjelenes.css").read_text(encoding="utf-8")
        template = (
            self.root / "szerver" / "alkalmazas" / "sablonok" / "kezdolap.html"
        ).read_text(encoding="utf-8")
        self.assertIn('id="today-tasks-button"', template)
        self.assertIn('id="today-tasks-button" class="icon-button"', template)
        self.assertIn("async function openTodayTasks", javascript)
        self.assertIn('data-notification-action="skip_15"', javascript)
        self.assertIn('data-notification-action="defer_24"', javascript)
        self.assertIn("data-move-notification", javascript)
        self.assertIn("priority-picker", javascript)
        self.assertIn("const todayCount = state.todayTasks.length", javascript)
        self.assertNotIn("today-notification-list", javascript)
        self.assertIn("data-jump-notification", javascript)
        self.assertIn("has-pending", javascript)
        self.assertIn("@keyframes notification-attention", stylesheet)
        self.assertNotIn("actionableGaps", javascript)
        self.assertNotIn("lobby-gaps", javascript)

    def test_offer_request_settings_and_contacts_are_project_protected(self) -> None:
        migration = (
            self.database_directory / "010_ajanlatkero_beallitasok.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("project_offer_request_settings", migration)
        self.assertIn("project_company_contacts", migration)
        self.assertIn("public.can_access_project(project_id, false)", migration)
        self.assertIn("public.can_access_project(project_id, true)", migration)
        self.assertIn("alter table public.project_company_contacts enable row level security", migration)
        self.assertIn("pg_get_serial_sequence", migration)

    def test_matrix_frontend_uses_flat_milestone_columns_and_continuous_months(self) -> None:
        static_directory = self.root / "szerver" / "alkalmazas" / "statikus"
        javascript = (static_directory / "alkalmazas.js").read_text(encoding="utf-8")
        modern_renderer = javascript.split("function renderContractMatrixModern", 1)[1].split(
            "function renderContractMatrix(", 1
        )[0]

        self.assertIn("function buildMatrixMonthGroups", javascript)
        self.assertIn("while (year < endYear || (year === endYear && month <= endMonth))", javascript)
        self.assertIn("const gridColumns = monthGroups.flatMap", modern_renderer)
        self.assertIn('colspan="${Math.max(1, month.columns.length)}"', modern_renderer)
        self.assertIn("monthGroups.map(monthHeader)", modern_renderer)
        self.assertIn("gridColumns.map(columnHeader)", modern_renderer)
        self.assertIn("gridColumns.map((column) => column ? moneyCell", modern_renderer)
        self.assertIn('data-milestone-id="${column.milestone_id || ""}"', modern_renderer)
        self.assertIn('data-column-code="${escapeHtml(column.code)}"', modern_renderer)
        self.assertIn('rowspan="2"', modern_renderer)
        self.assertNotIn("matrix-month-cell-stack", modern_renderer)
        self.assertNotIn("matrix-month-entry", modern_renderer)


if __name__ == "__main__":
    unittest.main()
