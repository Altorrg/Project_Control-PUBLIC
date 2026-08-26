from __future__ import annotations

from pathlib import Path
import unittest


class AIAssistantSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = Path(__file__).resolve().parents[1] / "alkalmazas"
        cls.template = (cls.application / "sablonok" / "kezdolap.html").read_text(encoding="utf-8")
        cls.script = (cls.application / "statikus" / "alkalmazas.js").read_text(encoding="utf-8")
        cls.styles = (cls.application / "statikus" / "megjelenes.css").read_text(encoding="utf-8")

    def test_assistant_is_part_of_the_authenticated_application_shell(self) -> None:
        app_start = self.template.index('<div id="app-view"')
        login_start = self.template.index('<section id="login-view"')
        assistant_start = self.template.index('id="ai-assistant-toggle"')
        self.assertGreater(assistant_start, app_start)
        self.assertGreater(app_start, login_start)

    def test_assistant_has_runtime_behaviour_and_responsive_styles(self) -> None:
        self.assertIn("function sendAIAssistantMessage", self.script)
        self.assertIn('api("/ai/assistant"', self.script)
        self.assertNotIn("window.PROJECT_CONTROL_AI_CONFIG", self.script)
        self.assertIn(".ai-assistant-panel", self.styles)
        self.assertIn("@media (max-width: 620px)", self.styles)

