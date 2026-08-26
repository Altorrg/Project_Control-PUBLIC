from __future__ import annotations

from typing import Any


class AppError(RuntimeError):
    status_code = 400

    def __init__(self, message: str, *, detail: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class AuthenticationError(AppError):
    status_code = 401


class AuthorizationError(AppError):
    status_code = 403


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class UpstreamError(AppError):
    status_code = 502


class ServiceUnavailableError(AppError):
    status_code = 503

