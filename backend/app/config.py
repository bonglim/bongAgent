"""Application configuration loaded from environment variables.

This module keeps API keys and runtime settings outside source code so the
project can grow from mock MVP mode into real LLM and internal-system
integrations without changing business logic modules.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime settings for the FastAPI application."""

    backend_cors_origins: str = "http://localhost:5173"
    llm_provider: str = "mock"
    openai_api_key: str = ""
    openai_model: str = "gpt-5.2"
    data_dir: Path = Path(__file__).resolve().parents[1] / "data"

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def cors_origin_list(self) -> list[str]:
        """Return CORS origins as a clean list for FastAPI middleware."""

        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Create the settings object once and reuse it across requests."""

    return Settings()
