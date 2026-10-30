from __future__ import annotations

import unittest
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from alkalmazas.beallitasok import Settings
from alkalmazas.hibak import AuthorizationError, UpstreamError
from alkalmazas.jogosultsagok import ensure_project_access
from alkalmazas.supabase_kapcsolat import SupabaseGateway
from alkalmazas.webszerver import create_app


class DemoProjectAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_guest_does_not_call_authenticated_only_rpc(self):
        class Gateway:
            async def select(self, table, token, **options):
                self.call = (table, token, options)
                return SimpleNamespace(data=[{"id": 7}])

            async def rpc(self, *_args, **_kwargs):
                raise AssertionError("The guest must not call the authenticated RPC")

        gateway = Gateway()
        await ensure_project_access(gateway, "guest_token", 7)
        self.assertEqual(gateway.call, (
            "projects", "guest_token", {
                "select": "id", "filters": {"id": "eq.7", "is_deleted": "eq.false"}, "limit": 1,
            },
        ))

    async def test_guest_cannot_open_a_project_hidden_by_rls(self):
        class Gateway:
            async def select(self, *_args, **_kwargs):
                return SimpleNamespace(data=[])

        for write in (False, True):
            with self.subTest(write=write), self.assertRaises(AuthorizationError):
                await ensure_project_access(Gateway(), "guest_token", 99, write=write)

    async def test_upstream_failure_is_not_treated_as_permission(self):
        class Gateway:
            async def select(self, *_args, **_kwargs):
                raise UpstreamError("Database unavailable")

        with self.assertRaises(UpstreamError):
            await ensure_project_access(Gateway(), "guest_token", 7)

    async def test_authenticated_users_keep_the_existing_rpc_gate(self):
        class Gateway:
            async def rpc(self, name, token, payload):
                self.call = (name, token, payload)
                return False

            async def select(self, *_args, **_kwargs):
                raise AssertionError("No guest fallback for authenticated users")

        gateway = Gateway()
        with self.assertRaises(AuthorizationError):
            await ensure_project_access(gateway, "real-user-jwt", 7, write=True)
        self.assertEqual(gateway.call, (
            "can_access_project", "real-user-jwt", {"target_project_id": 7, "write_access": True},
        ))


class DemoSettingsRegressionTests(unittest.TestCase):
    def test_data_page_loads_when_anonymous_tables_are_allowed_but_rpc_is_not(self):
        requests = []

        def transport(request):
            requests.append(request.url.path)
            if "/rpc/" in request.url.path:
                return httpx.Response(401, json={"message": "permission denied for function"})
            if request.url.path == "/rest/v1/projects":
                return httpx.Response(200, json=[{"id": 7, "name": "Synthetic demo"}])
            return httpx.Response(200, json=[])

        settings = Settings("https://example.supabase.co", "public-test-key")
        gateway = SupabaseGateway(settings, httpx.AsyncClient(transport=httpx.MockTransport(transport)))
        with TestClient(create_app(settings, gateway)) as client:
            response = client.get("/api/settings/7")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["project"]["id"], 7)
        self.assertFalse(any("/rpc/" in path for path in requests))
