from __future__ import annotations

from pathlib import Path
import unittest


class ScheduleKeySeedMigrationTests(unittest.TestCase):
    def test_unified_migration_contains_the_excel_seed_data(self) -> None:
        database_directory = Path(__file__).resolve().parents[2] / "adatbazis"
        sql = (database_directory / "014_utemterv_jelkulcsok_es_kapcsolatok.sql").read_text(encoding="utf-8")

        self.assertIn("create table if not exists public.schedule_keys", sql)
        self.assertIn("on conflict (code_key) do update", sql)
        self.assertIn("jsonb_build_object('row_count', 30)", sql)
        self.assertEqual(sql.count("    ('"), 30)
        self.assertIn("('DET'", sql)
        self.assertIn("('JOV ENG'", sql)


if __name__ == "__main__":
    unittest.main()
