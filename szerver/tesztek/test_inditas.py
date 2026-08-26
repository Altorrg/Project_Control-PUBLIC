from __future__ import annotations

from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch

import uvicorn

import inditas


class LocalStartTests(unittest.TestCase):
    def test_start_script_resolves_server_from_its_own_location(self):
        expected_root = Path(__file__).resolve().parents[2]
        self.assertEqual(inditas.ALKALMAZAS_GYOKER, expected_root)
        self.assertEqual(inditas.SZERVER_MAPPA, expected_root / "szerver")
        inditas.elokeszit_import_utvonalat()
        self.assertIn(str(expected_root / "szerver"), sys.path)

    def test_start_arguments_have_safe_local_defaults(self):
        args = inditas.argumentumok().parse_args([])
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8000)
        self.assertFalse(args.ujratoltes)

    def test_invalid_port_stops_before_reading_runtime_configuration(self):
        self.assertEqual(inditas.main(["--port", "70000", "--nincs-bongeszo"]), 2)

    def test_local_env_file_overrides_inherited_process_values(self):
        with patch("dotenv.load_dotenv") as load_environment:
            inditas.betolt_kornyezetet()

        load_environment.assert_called_once_with(
            inditas.ALKALMAZAS_GYOKER / ".env",
            encoding="utf-8-sig",
            override=True,
        )

    def test_main_starts_expected_asgi_application_without_environment_access(self):
        original_directory = Path.cwd()
        try:
            with (
                patch.object(inditas, "betolt_kornyezetet") as load_environment,
                patch.object(inditas, "ellenoriz_beallitasokat") as validate_settings,
                patch.object(uvicorn, "run") as run_server,
            ):
                result = inditas.main(["--host", "127.0.0.1", "--port", "8765", "--nincs-bongeszo"])
        finally:
            os.chdir(original_directory)

        self.assertEqual(result, 0)
        load_environment.assert_called_once_with()
        validate_settings.assert_called_once_with()
        run_server.assert_called_once()
        self.assertEqual(run_server.call_args.args[0], "alkalmazas.webszerver:app")
        self.assertEqual(run_server.call_args.kwargs["port"], 8765)


if __name__ == "__main__":
    unittest.main()
