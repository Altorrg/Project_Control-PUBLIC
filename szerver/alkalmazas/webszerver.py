from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .beallitasok import Settings
from .hibak import AppError
from .sebessegkorlat import SensitiveRateLimitMiddleware
from .supabase_kapcsolat import SupabaseGateway
from .teljesitmeny import (
    begin_request_metrics,
    current_request_metrics,
    end_request_metrics,
)


logger = logging.getLogger("project_control")


def create_app(settings: Settings | None = None, gateway: SupabaseGateway | None = None) -> FastAPI:
    runtime_settings = settings

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal runtime_settings
        runtime_settings = runtime_settings or Settings.from_environment()
        app.state.settings = runtime_settings
        app.state.supabase = gateway or SupabaseGateway(runtime_settings)
        yield
        if gateway is None:
            await app.state.supabase.close()

    app = FastAPI(
        title="Project Control Web API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    if runtime_settings:
        origins = runtime_settings.allowed_origins
    else:
        origins = ("http://localhost:8000", "http://127.0.0.1:8000")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )
    app.add_middleware(SensitiveRateLimitMiddleware)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        metrics_token = begin_request_metrics()
        started = perf_counter()
        try:
            response = await call_next(request)
            duration_ms = (perf_counter() - started) * 1000
            metrics = current_request_metrics()
        finally:
            end_request_metrics(metrics_token)
        response.headers["Server-Timing"] = (
            f"app;dur={duration_ms:.1f}, "
            f"supabase;dur={metrics['supabase_duration_ms']:.1f};"
            f'desc="{metrics["supabase_count"]} request"'
        )
        response.headers["X-Supabase-Request-Count"] = str(metrics["supabase_count"])
        if duration_ms >= 1000 and request.url.path.startswith("/api/"):
            logger.warning(
                "Slow API request method=%s path=%s status=%s duration_ms=%.1f "
                "supabase_count=%s supabase_duration_ms=%.1f supabase_paths=%s",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
                metrics["supabase_count"],
                metrics["supabase_duration_ms"],
                metrics["supabase_paths"],
            )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message, "detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled application error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Váratlan szerverhiba történt."},
        )

    from pathlib import Path
    from .vegpontok import api_router, oldalak

    app.include_router(api_router, prefix="/api")
    static_dir = Path(__file__).resolve().parent / "statikus"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(oldalak.router)
    return app


app = create_app()
