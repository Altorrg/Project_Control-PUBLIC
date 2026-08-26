from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from time import monotonic

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response


class SensitiveRateLimitMiddleware(BaseHTTPMiddleware):
    """Process-local defense layer for sensitive endpoints."""

    limits = (
        ("POST", "/api/auth/login", 10, 60),
        ("POST", "/api/auth/change-password", 5, 900),
        ("POST", "/api/engagements/import", 5, 300),
        ("POST", "/api/engagements/partner-requests", 30, 60),
        ("POST", "/api/engagements/assignments", 30, 60),
        ("PUT", "/api/admin/application-clock", 20, 60),
        ("POST", "/api/ai/assistant", 30, 60),
    )

    def __init__(self, app) -> None:
        super().__init__(app)
        self._requests: dict[tuple[str, str, str], deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    @classmethod
    def _limit_for(cls, method: str, path: str) -> tuple[str, int, int] | None:
        for target_method, prefix, maximum, window in cls.limits:
            if method == target_method and (path == prefix or path.startswith(prefix)):
                return prefix, maximum, window
        return None

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        selected = self._limit_for(request.method.upper(), request.url.path)
        if selected is None:
            return await call_next(request)

        prefix, maximum, window = selected
        client = request.client.host if request.client else "ismeretlen"
        key = (client, request.method.upper(), prefix)
        current = monotonic()
        async with self._lock:
            timestamps = self._requests[key]
            while timestamps and timestamps[0] <= current - window:
                timestamps.popleft()
            if len(timestamps) >= maximum:
                retry_after = max(1, int(window - (current - timestamps[0])))
                return JSONResponse(
                    status_code=429,
                    content={"error": "Túl sok kérés érkezett. Próbáld újra később."},
                    headers={"Retry-After": str(retry_after)},
                )
            timestamps.append(current)
        return await call_next(request)
