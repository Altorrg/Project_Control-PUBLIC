from __future__ import annotations

import asyncio
import unittest
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

from pydantic import ValidationError

from alkalmazas.adatmodellek.utemterv import (
    ContractSectionWrite,
    ProjectMilestoneWrite,
    ScheduleReorderRequest,
    ScheduleRowCreate,
)
from alkalmazas.hibak import ConflictError
from alkalmazas.szolgaltatasok.utemterv import (
    SCHEDULE_LINKED_DATE,
    add_calendar_months,
    calculate_milestone_dates,
    calculate_schedule,
    normalize_milestone,
)
from alkalmazas.vegpontok import utemterv as schedule_endpoints


def _row(
    row_id: int,
    position: int | str,
    phase_name: str,
    *,
    calc_type: str = "Naptári nap",
    days: int = 1,
    delay: int = 0,
) -> dict[str, Any]:
    return {
        "id": row_id,
        "position": position,
        "phase_name": phase_name,
        "reference_name": "Projekt kezdete",
        "days": days,
        "delay": delay,
        "calc_type": calc_type,
    }


class _Result:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _ScheduleGateway:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = {int(row["id"]): dict(row) for row in rows}
        self.updates: list[tuple[int, int]] = []

    async def select(
        self,
        table: str,
        _token: str,
        *,
        filters: dict[str, str] | None = None,
        order: str | None = None,
        **_kwargs: Any,
    ) -> _Result:
        assert table == "schedule_rows"
        rows = [dict(row) for row in self.rows.values()]
        if order:
            rows.sort(key=lambda row: (int(row["position"]), int(row["id"])))
        return _Result(rows)

    async def update(
        self,
        table: str,
        _token: str,
        data: dict[str, Any],
        filters: dict[str, str],
    ) -> list[dict[str, Any]]:
        assert table == "schedule_rows"
        row_id = int(filters["id"].removeprefix("eq."))
        position = int(data["position"])
        self.rows[row_id]["position"] = position
        self.updates.append((row_id, position))
        return [dict(self.rows[row_id])]


class _PhaseTimelineGateway:
    def __init__(self) -> None:
        self.rows = [
            _row(1, 10, "Első jelkulcs"),
            _row(2, 20, "Második jelkulcs"),
        ]
        self.rows[0]["financial_phase_no"] = 1
        self.rows[1]["financial_phase_no"] = 2

    async def select(self, table: str, _token: str, **_kwargs: Any) -> _Result:
        data = {
            "schedule_entries": [{"entry_date": "2026-01-02"}],
            "schedule_rows": self.rows,
            "calendar_exceptions": [],
            "project_milestones": [
                {"id": 11, "name": "Első mérföldkő", "phase_no": 1, "planned_date": "2026-01-05"},
                {"id": 12, "name": "Második mérföldkő", "phase_no": 2, "planned_date": "2026-01-08"},
            ],
        }[table]
        return _Result([dict(item) for item in data])


class _PhaseValidationGateway:
    async def select(self, table: str, _token: str, **_kwargs: Any) -> _Result:
        data = {
            "schedule_rows": [],
            "project_contract_sections": [{"section_no": 1}, {"section_no": 2}],
            "schedule_keys": [{"id": 9, "code": "E01"}],
        }[table]
        return _Result(data)


class _PhaseReferenceValidationGateway:
    async def select(self, table: str, _token: str, **_kwargs: Any) -> _Result:
        data = {
            "schedule_rows": [
                {
                    "id": 1,
                    "position": 10,
                    "phase_name": "Előző fázis",
                    "financial_phase_no": 1,
                }
            ],
            "project_contract_sections": [{"section_no": 1}, {"section_no": 2}],
            "schedule_keys": [{"id": 9, "code": "E01"}],
        }[table]
        return _Result(data)


class _DeleteScheduleGateway:
    def __init__(self) -> None:
        self.deleted: list[dict[str, str]] = []

    async def select(
        self,
        table: str,
        _token: str,
        *,
        filters: dict[str, str] | None = None,
        **_kwargs: Any,
    ) -> _Result:
        if table == "schedule_rows" and filters and filters.get("id") == "eq.7":
            return _Result([{"id": 7, "phase_name": "Törölhető jelkulcs"}])
        return _Result([])

    async def delete(
        self,
        table: str,
        _token: str,
        filters: dict[str, str],
    ) -> None:
        self.asserted_table = table
        self.deleted.append(filters)


class _ScheduleSaveGateway:
    def __init__(self) -> None:
        self.row = {
            "id": 7,
            "project_id": 1,
            "position": 10,
            "phase_name": "Eredeti jelkulcs",
            "reference_name": "Projekt kezdete",
            "financial_phase_no": 1,
            "schedule_key_id": 1,
            "phase_code": "RÉGI",
            "days": 1,
            "delay": 0,
            "manual_start": None,
            "calc_type": "Naptári nap",
        }

    async def select(
        self,
        table: str,
        _token: str,
        *,
        filters: dict[str, str] | None = None,
        **_kwargs: Any,
    ) -> _Result:
        if table == "schedule_rows":
            return _Result([dict(self.row)])
        if table == "project_contract_sections":
            return _Result([{"section_no": 1}])
        if table == "schedule_keys":
            return _Result([{"id": 9, "code": "E01"}])
        if table == "project_milestones":
            return _Result([])
        raise AssertionError(table)

    async def update(
        self,
        table: str,
        _token: str,
        data: dict[str, Any],
        _filters: dict[str, str],
    ) -> list[dict[str, Any]]:
        if table == "schedule_rows":
            self.row.update(data)
            return [dict(self.row)]
        if table == "project_milestones":
            return []
        raise AssertionError(table)


class ScheduleEnhancementTests(unittest.TestCase):
    def test_schedule_ui_uses_key_ids_and_hides_legacy_position_controls(self) -> None:
        script = (
            Path(__file__).parents[1] / "alkalmazas" / "statikus" / "alkalmazas.js"
        ).read_text(encoding="utf-8")
        start = script.index("async function renderSchedule()")
        end = script.index("function renderGantt(", start)
        schedule_ui = script[start:end]

        self.assertIn('data-field="schedule_key_id"', schedule_ui)
        self.assertIn('name="schedule_key_id"', schedule_ui)
        self.assertIn("Nincs tervezési mérföldkőhöz rendelve", schedule_ui)
        self.assertIn("Tervezési mérföldkő", schedule_ui)
        self.assertIn("Pénzügyi mérföldkövek", script)
        self.assertIn(
            "schedule_key_id: valueOrNull(data.schedule_key_id) === null ? null : Number(data.schedule_key_id)",
            schedule_ui,
        )
        self.assertNotIn('name="schedule_key_id" required', schedule_ui)
        self.assertNotIn(
            'data-action="new-schedule-row" ${scheduleKeys.length ? "" : "disabled"}',
            schedule_ui,
        )
        self.assertIn('value="legacy"', schedule_ui)
        self.assertIn('data-schedule-view="combined"', schedule_ui)
        self.assertIn('data-action="delete-schedule-row"', schedule_ui)
        self.assertIn('data-close', schedule_ui)
        self.assertIn('calc_type: "Naptári nap"', schedule_ui)
        self.assertIn("async function refreshScheduleCalculations()", schedule_ui)
        self.assertIn(
            "<th>Pénzügyi fázis</th><th>Tervezési mérföldkő</th><th>Ütemtervi elem</th>",
            schedule_ui,
        )
        self.assertIn('data-field="financial_phase_no"', schedule_ui)
        self.assertIn('name="financial_phase_no" required', schedule_ui)
        self.assertIn('function templateOptions(', schedule_ui)
        self.assertIn("sections.length === 1 ? sections[0].section_no", schedule_ui)
        self.assertNotIn('name="financial_milestone_id"', schedule_ui)
        self.assertNotIn('function saveFinancialMilestoneLink(', schedule_ui)
        self.assertNotIn("<th>Pénzügyi fázis</th><th>Típus</th>", schedule_ui)
        self.assertNotIn('data-action="open-schedule-row"', schedule_ui)
        self.assertIn('tr.addEventListener("dblclick"', schedule_ui)
        self.assertIn("const financialPhaseValue = canChooseFinancialPhase", schedule_ui)
        self.assertIn('id="new-schedule-row" class="primary-button"', schedule_ui)
        self.assertIn('financialPhaseChanged ? "Projekt kezdete"', schedule_ui)
        self.assertIn("gantt-planning-row", script)
        self.assertIn("gantt-planning-bar", script)
        self.assertIn("Tervezési mérföldkövek<small>", script)
        self.assertNotIn('type="button">Jelkulcsok</button>', script)
        self.assertIn("function renderMilestoneWorkspace(", script)
        self.assertIn("function wireMilestoneWorkspace(", script)
        self.assertIn("function renderProjectContractBase()", script)
        self.assertIn("function openContractSection(", script)
        self.assertIn("function openMilestone(", script)
        self.assertNotIn('data-field="section"', schedule_ui)
        self.assertNotIn("<th>Szakasz</th>", schedule_ui)
        self.assertNotIn("<th>Pozíció</th>", schedule_ui)
        self.assertNotIn("Mozgatás", schedule_ui)
        self.assertNotIn("showToast", schedule_ui)
        self.assertNotIn("state.currentProject", schedule_ui)
        self.assertNotIn("/api/schedules", schedule_ui)
        self.assertNotIn("renderRoute", schedule_ui)
        self.assertNotIn("openModal", schedule_ui)

        template = (
            Path(__file__).parents[1] / "alkalmazas" / "sablonok" / "kezdolap.html"
        ).read_text(encoding="utf-8")
        self.assertLess(
            template.index('data-module="settings"'),
            template.index('data-module="disciplines"'),
        )
        self.assertIn("megjelenes.css", template)
        self.assertIn("alkalmazas.js", template)

    def test_m1_planning_milestone_restore_is_idempotent_and_unassigned(self) -> None:
        migration = (
            Path(__file__).parents[2]
            / "adatbazis"
            / "015_m1_tervezesi_merfoldkovek_helyreallitasa.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("Tervindító egyeztetés", migration)
        self.assertIn("Kiviteli terv véglegesítés", migration)
        self.assertIn("on conflict (project_id, phase_name) do nothing", migration)
        self.assertIn("schedule_keys_assigned', false", migration)
        self.assertIn("insert into public.schedule_keys", migration)
        self.assertIn("create table if not exists public.schedule_keys", migration)
        self.assertIn("notify pgrst, 'reload schema'", migration)
        self.assertIn("active_schedule_key_count", migration)
        self.assertIn("m1_schedule_row_count", migration)
        self.assertEqual(migration.count("Naptári nap')"), 12)

    def test_contract_section_zero_is_valid(self) -> None:
        section = ContractSectionWrite(project_id=1, section_no=0)

        self.assertEqual(section.section_no, 0)
        with self.assertRaises(ValidationError):
            ContractSectionWrite(project_id=1, section_no=-1)

    def test_milestone_names_normalize_without_losing_legacy_name(self) -> None:
        legacy = ProjectMilestoneWrite(project_id=1, name="Régi név")
        detailed = "Első sor\n" + "\n".join(["részletes leírás"] * 200)
        extended = ProjectMilestoneWrite(
            project_id=1,
            short_name="Kártyacím",
            official_name="Hivatalos mérföldkőnév",
            description=detailed,
        )

        self.assertEqual(legacy.short_name, "Régi név")
        self.assertEqual(legacy.official_name, "Régi név")
        self.assertEqual(extended.name, "Hivatalos mérföldkőnév")
        self.assertEqual(extended.short_name, "Kártyacím")
        self.assertEqual(extended.description, detailed)
        self.assertEqual(
            normalize_milestone({"name": "Adatbázisból"})["official_name"],
            "Adatbázisból",
        )

    def test_milestone_can_belong_to_contract_section_zero(self) -> None:
        milestone = ProjectMilestoneWrite(
            project_id=1,
            name="Nulladik szakasz mérföldköve",
            phase_no=0,
        )

        self.assertEqual(milestone.phase_no, 0)

    def test_milestone_description_uses_long_text_validation(self) -> None:
        multiline = "Első sor\nMásodik sor"
        milestone = ProjectMilestoneWrite(
            project_id=1,
            name="Leírásos mérföldkő",
            description=multiline,
        )

        self.assertEqual(milestone.description, multiline)
        with self.assertRaises(ValidationError):
            ProjectMilestoneWrite(
                project_id=1,
                name="Túl hosszú leírás",
                description="x" * 5001,
            )

    def test_schedule_row_id_is_preferred_and_invalid_id_uses_legacy_fallback(self) -> None:
        linked = calculate_milestone_dates(
            [
                {
                    "id": 1,
                    "name": "Régi mérföldkő",
                    "short_name": "Kártya",
                    "official_name": "Hivatalos",
                    "date_type": SCHEDULE_LINKED_DATE,
                    "schedule_row_id": 7,
                    "reference_name": "Régi fázisnév",
                    "offset_days": 2,
                }
            ],
            [{"id": 7, "phase_name": "Átnevezett fázis", "end_date": date(2024, 5, 10)}],
        )
        fallback = calculate_milestone_dates(
            [
                {
                    "id": 2,
                    "name": "Legacy kapcsolat",
                    "date_type": SCHEDULE_LINKED_DATE,
                    "schedule_row_id": 99,
                    "reference_name": "Meglévő legacy fázis",
                    "offset_days": 2,
                }
            ],
            [
                {
                    "id": 8,
                    "phase_name": "Meglévő legacy fázis",
                    "end_date": date(2024, 6, 10),
                }
            ],
        )

        self.assertEqual(linked[0]["planned_date"], date(2024, 5, 12))
        self.assertEqual(linked[0]["reference_name"], "Átnevezett fázis")
        self.assertIsNone(fallback[0]["schedule_row_id"])
        self.assertEqual(fallback[0]["planned_date"], date(2024, 6, 12))

    def test_unresolved_schedule_link_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Árva kapcsolat.*Törölt fázis"):
            calculate_milestone_dates(
                [
                    {
                        "id": 2,
                        "name": "Árva kapcsolat",
                        "date_type": SCHEDULE_LINKED_DATE,
                        "schedule_row_id": 99,
                        "reference_name": "Törölt fázis",
                        "offset_days": 2,
                    }
                ],
                [],
            )

    def test_month_calculation_uses_calendar_months_and_clamps_month_end(self) -> None:
        common_year = calculate_schedule(
            [_row(1, 1, "Közös év", calc_type="Hónap")],
            date(2023, 1, 31),
        )
        leap_year = calculate_schedule(
            [_row(2, 1, "Szökőév", calc_type="Hónap")],
            date(2024, 1, 31),
        )
        two_months = calculate_schedule(
            [_row(3, 1, "Két hónap", calc_type="Hónap", days=2)],
            date(2024, 1, 31),
        )

        self.assertEqual(common_year[0]["end_date"], date(2023, 2, 28))
        self.assertEqual(leap_year[0]["end_date"], date(2024, 2, 29))
        self.assertEqual(two_months[0]["end_date"], date(2024, 3, 31))

    def test_calendar_month_helper_uses_the_same_policy_in_reverse(self) -> None:
        self.assertEqual(add_calendar_months(date(2024, 3, 31), -1), date(2024, 2, 29))
        self.assertEqual(add_calendar_months(date(2023, 3, 31), -1), date(2023, 2, 28))

    def test_existing_day_calculation_remains_inclusive(self) -> None:
        calendar_rows = calculate_schedule(
            [_row(1, 1, "Naptári", days=3)],
            date(2024, 1, 2),
        )
        workday_rows = calculate_schedule(
            [_row(2, 1, "Munka", calc_type="Munkanap", days=2)],
            date(2024, 1, 5),
        )

        self.assertEqual(calendar_rows[0]["end_date"], date(2024, 1, 4))
        self.assertEqual(workday_rows[0]["end_date"], date(2024, 1, 8))

    def test_model_accepts_optional_phase_fields_and_any_positive_position(self) -> None:
        legacy = ScheduleRowCreate(project_id=1, position=1, phase_name="Régi sor")
        extended = ScheduleRowCreate(
            project_id=1,
            position=10**18,
            section="",
            phase_code="F-001",
            phase_name="Új sor",
            calc_type="Hónap",
        )

        self.assertIsNone(legacy.section)
        self.assertIsNone(legacy.phase_code)
        self.assertNotIn("section", legacy.model_fields_set)
        self.assertEqual(extended.section, "")
        self.assertEqual(extended.phase_code, "F-001")

        for invalid_position in (0, -1):
            with self.assertRaises(ValidationError):
                ScheduleRowCreate(
                    project_id=1,
                    position=invalid_position,
                    phase_name="Hibás",
                )

    def test_schedule_sort_is_numeric_then_by_id(self) -> None:
        calculated = calculate_schedule(
            [
                _row(20, "10", "Tízes"),
                _row(9, "2", "Kettes később"),
                _row(1, "2", "Kettes előbb"),
            ],
            date(2024, 1, 2),
        )

        self.assertEqual([row["id"] for row in calculated], [1, 9, 20])

    def test_financial_phase_is_preserved_and_timeline_can_filter_it(self) -> None:
        timeline_gateway = _PhaseTimelineGateway()
        combined = asyncio.run(schedule_endpoints._timeline(1, "token", timeline_gateway))
        first_phase = asyncio.run(
            schedule_endpoints._timeline(1, "token", timeline_gateway, financial_phase_no=1)
        )

        self.assertEqual([row["id"] for row in combined["rows"]], [1, 2])
        self.assertEqual([row["id"] for row in first_phase["rows"]], [1])
        self.assertEqual([row["id"] for row in first_phase["milestones"]], [11])
        self.assertEqual(first_phase["financial_phase_no"], 1)

    def test_new_schedule_row_requires_existing_financial_phase_and_resolves_key(self) -> None:
        payload = ScheduleRowCreate(
            project_id=1,
            position=10,
            financial_phase_no=2,
            schedule_key_id=9,
            phase_name="Új jelkulcs",
        )
        asyncio.run(
            schedule_endpoints._validate_schedule_row(
                1, payload, "token", _PhaseValidationGateway()
            )
        )

        self.assertEqual(payload.phase_code, "E01")
        invalid = ScheduleRowCreate(
            project_id=1,
            position=10,
            financial_phase_no=3,
            phase_name="Nem létező fázis",
        )
        with self.assertRaises(ConflictError):
            asyncio.run(
                schedule_endpoints._validate_schedule_row(
                    1, invalid, "token", _PhaseValidationGateway()
                )
            )

    def test_schedule_reference_cannot_cross_financial_phases(self) -> None:
        payload = ScheduleRowCreate(
            project_id=1,
            position=20,
            financial_phase_no=2,
            schedule_key_id=9,
            phase_name="Második fázis sora",
            reference_name="Előző fázis",
        )

        with self.assertRaisesRegex(ConflictError, "ugyanazon pénzügyi fázis"):
            asyncio.run(
                schedule_endpoints._validate_schedule_row(
                    1, payload, "token", _PhaseReferenceValidationGateway()
                )
            )

    def test_unreferenced_schedule_row_can_be_deleted(self) -> None:
        gateway = _DeleteScheduleGateway()

        result = asyncio.run(
            schedule_endpoints.delete_row(1, 7, "token", "csrf", gateway=gateway)
        )

        self.assertEqual(result, {"deleted": True})
        self.assertEqual(gateway.asserted_table, "schedule_rows")
        self.assertEqual(gateway.deleted, [{"id": "eq.7", "project_id": "eq.1"}])

    def test_schedule_key_id_is_persisted_on_update(self) -> None:
        gateway = _ScheduleSaveGateway()
        payload = ScheduleRowCreate(
            project_id=1,
            position=10,
            financial_phase_no=1,
            schedule_key_id=9,
            phase_name="Frissített jelkulcs",
        )

        async def no_refresh(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
            return []

        with patch.object(schedule_endpoints, "_refresh_dynamic_milestones", no_refresh):
            result = asyncio.run(
                schedule_endpoints.update_row(1, 7, payload, "token", "csrf", gateway=gateway)
            )

        self.assertEqual(result["schedule_key_id"], 9)
        self.assertEqual(result["phase_code"], "E01")
        self.assertEqual(gateway.row["schedule_key_id"], 9)
        self.assertEqual(gateway.row["phase_name"], "Frissített jelkulcs")

    def test_removing_schedule_key_turns_row_into_planning_milestone(self) -> None:
        gateway = _ScheduleSaveGateway()
        payload = ScheduleRowCreate(
            project_id=1,
            position=10,
            financial_phase_no=1,
            schedule_key_id=None,
            phase_name="Tervezési mérföldkő",
        )

        async def no_refresh(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
            return []

        with patch.object(schedule_endpoints, "_refresh_dynamic_milestones", no_refresh):
            result = asyncio.run(
                schedule_endpoints.update_row(1, 7, payload, "token", "csrf", gateway=gateway)
            )

        self.assertIsNone(result["schedule_key_id"])
        self.assertIsNone(result["phase_code"])
        self.assertEqual(gateway.row["phase_name"], "Tervezési mérföldkő")

    def test_reorder_renumbers_sparse_duplicate_positions_without_collisions(self) -> None:
        gateway = _ScheduleGateway(
            [
                _row(1, 100, "Első"),
                _row(2, 5, "Második"),
                _row(3, 5, "Harmadik"),
            ]
        )

        async def no_refresh(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
            return []

        with patch.object(schedule_endpoints, "_refresh_dynamic_milestones", no_refresh):
            result = asyncio.run(
                schedule_endpoints.reorder_rows(
                    1,
                    ScheduleReorderRequest(row_ids=[3, 1, 2]),
                    "token",
                    "csrf",
                    gateway=gateway,
                )
            )

        self.assertEqual([row["id"] for row in result], [3, 1, 2])
        self.assertEqual([row["position"] for row in result], [10, 20, 30])
        self.assertEqual(gateway.updates, [(3, 10), (1, 20), (2, 30)])

    def test_reorder_rejects_duplicate_row_ids(self) -> None:
        gateway = _ScheduleGateway([_row(1, 10, "Első"), _row(2, 20, "Második")])

        with self.assertRaises(ConflictError):
            asyncio.run(
                schedule_endpoints.reorder_rows(
                    1,
                    ScheduleReorderRequest(row_ids=[1, 1]),
                    "token",
                    "csrf",
                    gateway=gateway,
                )
            )

        self.assertEqual(gateway.updates, [])


if __name__ == "__main__":
    unittest.main()
