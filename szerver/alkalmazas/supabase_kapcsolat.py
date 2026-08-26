from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import logging
from time import monotonic
from time import perf_counter
from typing import Any, Mapping
from urllib.parse import quote
from urllib.parse import urlparse

import httpx

from .beallitasok import Settings
from .hibak import AuthenticationError, AuthorizationError, ConflictError, NotFoundError, UpstreamError
from .teljesitmeny import record_supabase_request


logger = logging.getLogger("project_control.supabase")


@dataclass(slots=True)
class SupabaseResponse:
    data: Any
    count: int | None = None


class SupabaseGateway:
    """Small async gateway that forwards the user's JWT so Supabase RLS remains active."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            follow_redirects=False,
        )
        self._identity_cache: dict[str, tuple[float, dict[str, Any], dict[str, Any]]] = {}
        self._identity_locks: dict[str, asyncio.Lock] = {}

    async def close(self) -> None:
        self._identity_cache.clear()
        self._identity_locks.clear()
        if self._owns_client:
            await self.client.aclose()

    async def authenticated_identity(
        self,
        access_token: str,
        *,
        cache_seconds: float = 10.0,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Coalesce concurrent identity checks while Supabase still enforces RLS per query."""
        cache_key = hashlib.sha256(access_token.encode("utf-8")).hexdigest()
        now = monotonic()
        cached = self._identity_cache.get(cache_key)
        if cached and cached[0] > now:
            return dict(cached[1]), dict(cached[2])

        lock = self._identity_locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            now = monotonic()
            cached = self._identity_cache.get(cache_key)
            if cached and cached[0] > now:
                return dict(cached[1]), dict(cached[2])

            auth_data = await self.auth_user(access_token)
            user_id = str(auth_data.get("id") or "")
            if not user_id:
                return auth_data, {}
            profile_response = await self.select(
                "profiles",
                access_token,
                filters={"id": f"eq.{user_id}"},
                limit=1,
            )
            profile = dict(profile_response.data[0]) if profile_response.data else {}
            self._identity_cache[cache_key] = (
                monotonic() + max(0.0, cache_seconds),
                dict(auth_data),
                profile,
            )
            if len(self._identity_cache) > 1000:
                expired = [key for key, value in self._identity_cache.items() if value[0] <= monotonic()]
                for key in expired:
                    self._identity_cache.pop(key, None)
                    self._identity_locks.pop(key, None)
            return dict(auth_data), dict(profile)

    def _headers(
        self,
        access_token: str | None = None,
        *,
        prefer: str | None = None,
        content_type: str = "application/json",
    ) -> dict[str, str]:
        bearer = self.settings.supabase_anon_key
        if access_token and access_token != "guest_token":
            bearer = access_token
        headers = {
            "apikey": self.settings.supabase_anon_key,
            "Authorization": f"Bearer {bearer}",
            "Content-Type": content_type,
            "Accept": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    async def _request(
        self,
        method: str,
        url: str,
        *,
        access_token: str | None = None,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        prefer: str | None = None,
    ) -> httpx.Response:
        request_headers = self._headers(access_token, prefer=prefer)
        if headers:
            request_headers.update(headers)
        started = perf_counter()
        request_path = urlparse(url).path
        try:
            response = await self.client.request(
                method,
                url,
                params=params,
                json=json,
                content=content,
                headers=request_headers,
            )
        except httpx.HTTPError as exc:
            duration_ms = (perf_counter() - started) * 1000
            record_supabase_request(request_path, duration_ms)
            logger.warning(
                "Supabase network error method=%s path=%s duration_ms=%.1f",
                method,
                request_path,
                duration_ms,
            )
            raise UpstreamError("A Supabase szolgáltatás jelenleg nem érhető el.") from exc
        duration_ms = (perf_counter() - started) * 1000
        record_supabase_request(request_path, duration_ms)
        if duration_ms >= 500 or response.status_code >= 400:
            logger.warning(
                "Supabase request method=%s path=%s status=%s duration_ms=%.1f",
                method,
                request_path,
                response.status_code,
                duration_ms,
            )

        error_detail: dict[str, Any] | None = None
        if response.status_code >= 400:
            try:
                parsed_detail = response.json()
            except ValueError:
                parsed_detail = None
            error_detail = parsed_detail if isinstance(parsed_detail, dict) else {
                "status": response.status_code
            }

        if response.status_code == 401:
            raise AuthenticationError("A munkamenet lejárt vagy nincs megfelelő jogosultság.")
        if response.status_code == 403:
            raise AuthorizationError("A művelethez nincs megfelelő jogosultság.")
        if response.status_code == 404:
            raise NotFoundError("A kért rekord nem található.", detail=error_detail)
        if response.status_code == 409:
            raise ConflictError("Az adat ütközik egy már létező rekorddal.")
        if response.is_error:
            raise UpstreamError("A Supabase elutasította a műveletet.", detail=error_detail)
        return response

    async def sign_in(self, email: str, password: str) -> dict[str, Any]:
        response = await self._request(
            "POST",
            f"{self.settings.supabase_url}/auth/v1/token",
            params={"grant_type": "password"},
            json={"email": email, "password": password},
        )
        return response.json()

    async def refresh_session(self, refresh_token: str) -> dict[str, Any]:
        response = await self._request(
            "POST",
            f"{self.settings.supabase_url}/auth/v1/token",
            params={"grant_type": "refresh_token"},
            json={"refresh_token": refresh_token},
        )
        return response.json()

    async def auth_user(self, access_token: str) -> dict[str, Any]:
        response = await self._request(
            "GET",
            f"{self.settings.supabase_url}/auth/v1/user",
            access_token=access_token,
        )
        return response.json()

    async def update_password(
        self,
        access_token: str,
        current_password: str,
        new_password: str,
    ) -> dict[str, Any]:
        response = await self._request(
            "PUT",
            f"{self.settings.supabase_url}/auth/v1/user",
            access_token=access_token,
            json={
                "current_password": current_password,
                "password": new_password,
            },
        )
        return response.json()

    async def select(
        self,
        table: str,
        access_token: str,
        *,
        select: str = "*",
        filters: Mapping[str, str] | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        count: bool = False,
    ) -> SupabaseResponse:
        params: dict[str, Any] = {"select": select}
        params.update(filters or {})
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(limit)
        if offset is not None:
            params["offset"] = str(offset)
        prefer = "count=exact" if count else None
        response = await self._request(
            "GET",
            f"{self.settings.supabase_url}/rest/v1/{quote(table, safe='')}",
            access_token=access_token,
            params=params,
            prefer=prefer,
        )
        total = None
        content_range = response.headers.get("content-range", "")
        if "/" in content_range and content_range.rsplit("/", 1)[1].isdigit():
            total = int(content_range.rsplit("/", 1)[1])
        return SupabaseResponse(response.json(), total)

    async def insert(
        self,
        table: str,
        access_token: str,
        payload: Mapping[str, Any] | list[Mapping[str, Any]],
    ) -> Any:
        response = await self._request(
            "POST",
            f"{self.settings.supabase_url}/rest/v1/{quote(table, safe='')}",
            access_token=access_token,
            json=payload,
            prefer="return=representation",
        )
        return response.json()

    async def update(
        self,
        table: str,
        access_token: str,
        payload: Mapping[str, Any],
        filters: Mapping[str, str],
    ) -> Any:
        response = await self._request(
            "PATCH",
            f"{self.settings.supabase_url}/rest/v1/{quote(table, safe='')}",
            access_token=access_token,
            params=filters,
            json=payload,
            prefer="return=representation",
        )
        return response.json()

    async def upsert(
        self,
        table: str,
        access_token: str,
        payload: Mapping[str, Any] | list[Mapping[str, Any]],
        *,
        on_conflict: str | None = None,
    ) -> Any:
        params = {"on_conflict": on_conflict} if on_conflict else None
        response = await self._request(
            "POST",
            f"{self.settings.supabase_url}/rest/v1/{quote(table, safe='')}",
            access_token=access_token,
            params=params,
            json=payload,
            prefer="resolution=merge-duplicates,return=representation",
        )
        return response.json()

    async def delete(
        self,
        table: str,
        access_token: str,
        filters: Mapping[str, str],
    ) -> Any:
        response = await self._request(
            "DELETE",
            f"{self.settings.supabase_url}/rest/v1/{quote(table, safe='')}",
            access_token=access_token,
            params=filters,
            prefer="return=representation",
        )
        return response.json()

    async def rpc(
        self,
        function_name: str,
        access_token: str,
        payload: Mapping[str, Any] | None = None,
    ) -> Any:
        response = await self._request(
            "POST",
            f"{self.settings.supabase_url}/rest/v1/rpc/{quote(function_name, safe='')}",
            access_token=access_token,
            json=payload or {},
            prefer="return=representation",
        )
        return response.json() if response.content else None

    async def upload(
        self,
        bucket: str,
        object_path: str,
        access_token: str,
        content: bytes,
        content_type: str,
    ) -> dict[str, Any]:
        response = await self._request(
            "POST",
            f"{self.settings.supabase_url}/storage/v1/object/{quote(bucket, safe='')}/{quote(object_path)}",
            access_token=access_token,
            content=content,
            headers={"Content-Type": content_type, "x-upsert": "false"},
        )
        return response.json()

    async def signed_download_url(
        self,
        bucket: str,
        object_path: str,
        access_token: str,
        *,
        expires_in: int = 60,
    ) -> str:
        response = await self._request(
            "POST",
            f"{self.settings.supabase_url}/storage/v1/object/sign/{quote(bucket, safe='')}/{quote(object_path)}",
            access_token=access_token,
            json={"expiresIn": expires_in},
        )
        payload = response.json()
        signed_path = payload.get("signedURL") or payload.get("signedUrl")
        if not signed_path:
            raise UpstreamError("A csatolmányhoz nem sikerült ideiglenes hivatkozást létrehozni.")
        if str(signed_path).startswith(("http://", "https://")):
            return str(signed_path)
        return f"{self.settings.supabase_url}/storage/v1{signed_path}"
