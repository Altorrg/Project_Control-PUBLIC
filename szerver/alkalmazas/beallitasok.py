from __future__ import annotations

from dataclasses import dataclass
import os


PUBLIC_KEY_VARIABLES = (
    "SUPABASE_ANON_KEY",
    "SUPABASE_PUBLISHABLE_KEY",
    "SUPABASE_PUBLIC_KEY",
    "SUPABASE_KEY",
    "NEXT_PUBLIC_SUPABASE_ANON_KEY",
    "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY",
    "VITE_SUPABASE_ANON_KEY",
    "VITE_SUPABASE_PUBLISHABLE_KEY",
)


class ConfigurationError(RuntimeError):
    """Raised when required runtime configuration is missing."""


@dataclass(frozen=True, slots=True)
class Settings:
    supabase_url: str
    supabase_anon_key: str
    app_name: str = "Project Control"
    environment: str = "development"
    cookie_secure: bool = False
    allowed_origins: tuple[str, ...] = ("http://localhost:8000", "http://127.0.0.1:8000")
    max_upload_bytes: int = 20 * 1024 * 1024
    request_timeout_seconds: float = 30.0
    ai_provider: str = ""
    ai_api_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""
    ai_request_timeout_seconds: float = 300.0

    @property
    def ai_configured(self) -> bool:
        return bool(
            self.ai_provider
            and self.ai_api_base_url
            and self.ai_api_key
            and self.ai_model
        )

    @classmethod
    def from_environment(cls) -> "Settings":
        """Load runtime values without ever logging secrets."""
        url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        anon_key = next(
            (
                value
                for name in PUBLIC_KEY_VARIABLES
                if (value := os.getenv(name, "").strip())
            ),
            "",
        )
        missing = []
        if not url:
            missing.append("SUPABASE_URL")
        if not anon_key:
            missing.append("SUPABASE_ANON_KEY vagy SUPABASE_PUBLISHABLE_KEY")
        if missing:
            raise ConfigurationError(
                "Hiányzik a futási konfiguráció: " + ", ".join(missing)
            )

        origins = tuple(
            item.strip()
            for item in os.getenv(
                "ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
            ).split(",")
            if item.strip()
        )
        environment = os.getenv("APP_ENV", "development").strip().lower()
        return cls(
            supabase_url=url,
            supabase_anon_key=anon_key,
            environment=environment,
            cookie_secure=os.getenv("COOKIE_SECURE", "").strip().lower()
            in {"1", "true", "yes", "on"},
            allowed_origins=origins,
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024))),
            request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30")),
            ai_provider=os.getenv("AI_PROVIDER", "").strip(),
            ai_api_base_url=os.getenv("AI_API_BASE_URL", "").strip().rstrip("/"),
            ai_api_key=os.getenv("AI_API_KEY", "").strip(),
            ai_model=os.getenv("AI_MODEL", "").strip(),
            ai_request_timeout_seconds=max(
                300.0,
                float(os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "300")),
            ),
        )
