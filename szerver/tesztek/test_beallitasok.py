from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from alkalmazas.beallitasok import ConfigurationError, PUBLIC_KEY_VARIABLES, Settings


class SettingsTests(unittest.TestCase):
    def test_all_supported_public_key_names_are_accepted(self):
        for variable_name in PUBLIC_KEY_VARIABLES:
            with self.subTest(variable_name=variable_name), patch.dict(
                os.environ,
                {"SUPABASE_URL": "https://pelda.supabase.co", variable_name: "public-test-key"},
                clear=True,
            ):
                settings = Settings.from_environment()
                self.assertEqual(settings.supabase_anon_key, "public-test-key")

    def test_service_role_name_is_not_accepted_as_public_key(self):
        with patch.dict(
            os.environ,
            {"SUPABASE_URL": "https://pelda.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "secret"},
            clear=True,
        ):
            with self.assertRaises(ConfigurationError):
                Settings.from_environment()

    def test_ai_timeout_is_never_shorter_than_five_minutes(self):
        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://pelda.supabase.co",
                "SUPABASE_KEY": "public-test-key",
                "AI_REQUEST_TIMEOUT_SECONDS": "60",
            },
            clear=True,
        ):
            settings = Settings.from_environment()

        self.assertEqual(settings.ai_request_timeout_seconds, 300.0)


if __name__ == "__main__":
    unittest.main()
