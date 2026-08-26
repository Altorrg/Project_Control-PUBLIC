from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any


_request_metrics: ContextVar[dict[str, Any] | None] = ContextVar(
    "project_control_request_metrics",
    default=None,
)


def begin_request_metrics() -> Token:
    return _request_metrics.set(
        {
            "supabase_count": 0,
            "supabase_duration_ms": 0.0,
            "supabase_paths": {},
        }
    )


def record_supabase_request(path: str, duration_ms: float) -> None:
    metrics = _request_metrics.get()
    if metrics is None:
        return
    metrics["supabase_count"] += 1
    metrics["supabase_duration_ms"] += duration_ms
    paths = metrics["supabase_paths"]
    paths[path] = paths.get(path, 0) + 1


def current_request_metrics() -> dict[str, Any]:
    metrics = _request_metrics.get()
    return dict(metrics) if metrics is not None else {
        "supabase_count": 0,
        "supabase_duration_ms": 0.0,
        "supabase_paths": {},
    }


def end_request_metrics(token: Token) -> None:
    _request_metrics.reset(token)
