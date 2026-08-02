"""
app/settings.py
---------------
Central configuration via pydantic-settings.
All values are loaded from environment variables or a .env file.
Startup will abort with a clear message if any required key is missing.
"""

from __future__ import annotations

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Supabase / Database ──────────────────────────────────────────────────
    # Use the asyncpg driver for async SQLAlchemy.
    # Example: postgresql+asyncpg://postgres.<project>:<password>@<host>:5432/postgres
    DATABASE_URL: str

    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""

    # ── NVIDIA NIM ───────────────────────────────────────────────────────────
    NVIDIA_API_KEY: str
    NVIDIA_API_URL: str = "https://integrate.api.nvidia.com/v1/chat/completions"
    NVIDIA_EMBED_MODEL: str = "nvidia/nv-embed-v2"
    NVIDIA_GEN_MODEL: str = "nvidia/nemotron-70b-instruct"
    NVIDIA_EMBED_DIM: int = 768

    # ── WhatsApp – Meta Cloud API ────────────────────────────────────────────
    # Leave empty until credentials are available; the webhook stub works
    # without them (GET verification still functions with META_VERIFY_TOKEN).
    META_VERIFY_TOKEN: str = ""
    META_ACCESS_TOKEN: str = ""
    META_PHONE_NUMBER_ID: str = ""
    META_GRAPH_API_URL: str = "https://graph.facebook.com/v19.0"

    # ── Rate Limiting ────────────────────────────────────────────────────────
    # Maximum Nemotron-OCR calls allowed per minute across all users.
    OCR_RATE_LIMIT_PER_MINUTE: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Validators ───────────────────────────────────────────────────────────

    @field_validator("DATABASE_URL")
    @classmethod
    def must_use_asyncpg(cls, v: str) -> str:
        """
        Ensure the DATABASE_URL uses the asyncpg driver.
        Automatically patch plain postgresql:// URLs to avoid silent failures.
        """
        if v.startswith("postgresql://") or v.startswith("postgres://"):
            # Replace scheme so asyncio engine works correctly
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
            v = v.replace("postgres://", "postgresql+asyncpg://", 1)
        elif v.startswith("sqlite:///"):
            # Tests often use sqlite:// URLs; convert to async driver URL.
            v = v.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        return v

    @model_validator(mode="after")
    def check_required_secrets(self) -> "Settings":
        missing: list[str] = []
        if not self.DATABASE_URL:
            missing.append("DATABASE_URL")
        if not self.NVIDIA_API_KEY:
            missing.append("NVIDIA_API_KEY")
        if missing:
            raise ValueError(
                f"Missing required environment variable(s): {', '.join(missing)}. "
                "Set them in your .env file or the system environment."
            )
        return self


# Module-level singleton – import this everywhere
settings = Settings()  # type: ignore[call-arg]
