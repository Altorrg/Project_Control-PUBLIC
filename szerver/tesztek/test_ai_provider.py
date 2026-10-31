from __future__ import annotations

import json
import unittest

import httpx

from alkalmazas.adatmodellek.ai_asszisztens import (
    AIAssistantHistoryMessage,
    AIAssistantRequest,
    AIAssistantResponse,
)
from alkalmazas.beallitasok import Settings
from alkalmazas.hibak import ServiceUnavailableError
from alkalmazas.szolgaltatasok.ai_provider import generate_ai_assistant_response


class AIProviderTests(unittest.IsolatedAsyncioTestCase):
    def test_complete_model_answer_can_exceed_legacy_five_thousand_character_limit(self) -> None:
        result = AIAssistantResponse(answer="a" * 8000, request_id="test-request")
        self.assertEqual(len(result.answer), 8000)

    async def test_generic_provider_uses_internal_oracle_contract(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["api_key"] = request.headers.get("x-api-key")
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"valasz": "Oracle valasz."})

        settings = Settings(
            "https://example.supabase.co",
            "public-test-key",
            ai_provider="generic",
            ai_api_base_url="http://oracle.example:8000/api/kerdes",
            ai_api_key="secret-test-key",
            ai_model="internal-test-model",
        )
        payload = AIAssistantRequest(message="Hogyan hasznaljam az utemtervet?", project_id=7, module="schedule",
            history=[AIAssistantHistoryMessage(role="assistant", content="Korábbi hosszú válasz")])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await generate_ai_assistant_response(settings, payload, client=client)

        self.assertEqual(result.answer, "Oracle valasz.")
        self.assertEqual(captured["url"], "http://oracle.example:8000/api/kerdes")
        self.assertEqual(captured["api_key"], "secret-test-key")
        body = captured["body"]
        self.assertEqual("Hogyan hasznaljam az utemtervet?", body["kerdes"])
        self.assertEqual(body["model"], "internal-test-model")

    async def test_oracle_document_sources_are_preserved_and_bounded(self) -> None:
        settings = Settings("https://example.supabase.co", "public-test-key", ai_provider="generic",
            ai_api_base_url="http://oracle.example:8000/api/kerdes", ai_api_key="test-key", ai_model="test")
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"valasz": "Dokumentált válasz.", "forrasok": ["utemterv.md", "utemterv.md", None, {}, "x" * 300]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await generate_ai_assistant_response(settings, AIAssistantRequest(message="Ütemterv"), client=client)
        self.assertEqual([s.label for s in result.sources], ["utemterv.md", "x" * 255])

    async def test_provider_timeout_has_actionable_message_without_secret(self) -> None:
        settings = Settings("https://example.supabase.co", "public-test-key", ai_provider="generic",
            ai_api_base_url="http://oracle.example:8000/api/kerdes", ai_api_key="secret-test-key", ai_model="test")
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("secret-test-key", request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(ServiceUnavailableError) as caught:
                await generate_ai_assistant_response(settings, AIAssistantRequest(message="Ütemterv"), client=client)
        self.assertIn("nem válaszolt időben", str(caught.exception))
        self.assertNotIn("secret-test-key", str(caught.exception))

    async def test_html_error_page_is_not_an_assistant_answer(self) -> None:
        settings = Settings("https://example.supabase.co", "public-test-key", ai_provider="generic",
            ai_api_base_url="http://oracle.example:8000/api/kerdes", ai_api_key="test-key", ai_model="test")
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="<!doctype html><html>Gateway page</html>"))) as client:
            with self.assertRaises(ServiceUnavailableError):
                await generate_ai_assistant_response(settings, AIAssistantRequest(message="Ütemterv"), client=client)

    async def test_openai_compatible_request_uses_model_and_chat_messages(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["authorization"] = request.headers.get("authorization")
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"choices": [{"message": {"content": "Rendben."}}]})

        settings = Settings(
            "https://example.supabase.co",
            "public-test-key",
            ai_provider="openrouter",
            ai_api_base_url="https://openrouter.ai/api/v1",
            ai_api_key="secret-test-key",
            ai_model="test/model",
        )
        payload = AIAssistantRequest(
            message="Mi a következő lépés?",
            project_id=7,
            module="schedule",
            history=[AIAssistantHistoryMessage(role="user", content="Korábbi kérdés")],
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await generate_ai_assistant_response(settings, payload, client=client)

        self.assertEqual(result.answer, "Rendben.")
        self.assertEqual(captured["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(captured["authorization"], "Bearer secret-test-key")
        body = captured["body"]
        self.assertEqual(body["model"], "test/model")
        self.assertEqual(body["messages"][-1], {"role": "user", "content": "Mi a következő lépés?"})

    async def test_gemini_request_and_response_are_supported(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["api_key"] = request.headers.get("x-goog-api-key")
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": "Gemini válasz."}]}}]},
            )

        settings = Settings(
            "https://example.supabase.co",
            "public-test-key",
            ai_provider="gemini",
            ai_api_base_url="https://generativelanguage.googleapis.com/v1beta",
            ai_api_key="secret-test-key",
            ai_model="gemini-test",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await generate_ai_assistant_response(
                settings,
                AIAssistantRequest(message="Teszt"),
                client=client,
            )

        self.assertEqual(result.answer, "Gemini válasz.")
        self.assertEqual(
            captured["url"],
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent",
        )
        self.assertEqual(captured["api_key"], "secret-test-key")


if __name__ == "__main__":
    unittest.main()
