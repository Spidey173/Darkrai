import ast
import json
import os
import re
from typing import Any, List, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

def parse_cors(v: Any) -> List[str]:
    """Helper to parse list of origins from environment variables flexibly."""
    if isinstance(v, list):
        return [str(item).strip() for item in v if item]
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return []
        if v.startswith("[") and v.endswith("]"):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(i).strip() for i in parsed]
            except Exception:
                try:
                    parsed = ast.literal_eval(v)
                    if isinstance(parsed, list):
                        return [str(i).strip() for i in parsed]
                except Exception:
                    pass
        # Comma-separated or single URL string
        return [i.strip() for i in v.split(",") if i.strip()]
    return [str(v)]

def sanitize_database_url(v: Any) -> str:
    """Sanitizes DATABASE_URL for async drivers (asyncpg for PostgreSQL, aiosqlite for SQLite)."""
    if isinstance(v, str):
        if v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif v.startswith("sqlite://") and not v.startswith("sqlite+aiosqlite://"):
            v = v.replace("sqlite://", "sqlite+aiosqlite://", 1)
        if "sslmode=" in v:
            v = v.replace("sslmode=", "ssl=")
        v = re.sub(r'[&?]channel_binding=[^&]*', '', v)
    return str(v)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore"
    )

    APP_NAME: str = "Darkrai"
    APP_ENV: str = "development"
    DEBUG: bool = True

    # Security Config with safe development/testing fallbacks
    SECRET_KEY: str = "darkrai-dev-secret-key-32bytes-for-development"
    ENCRYPTION_KEY: str = "DgMHhFBzYTgCBS_Y9pSwCl5_ObmQUmD1i528mpYdPTQ="

    # Database config (defaults to local aiosqlite for zero-config startup and test isolation)
    DATABASE_URL: str = "sqlite+aiosqlite:///./darkrai.db"

    # Serverless runtime detection (Vercel sets VERCEL=1)
    VERCEL: bool = False

    # Redis Queue config (defaults to standard Redis URL, with resilient async in-memory fallback)
    REDIS_URL: str = "redis://localhost:6379/0"
    USE_REDIS_QUEUE: bool = True

    # CORS settings (accepts comma-separated, JSON array string, single URL, or list)
    BACKEND_CORS_ORIGINS: Union[str, List[str]] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # External APIs (Optional for initial bootstrap, but present in config)
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    GITHUB_WEBHOOK_SECRET: str = ""
    
    # Optional LLM API Keys for AI PR reviews
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # Webhook callback configuration base
    WEBHOOK_BASE_URL: str = "http://localhost:8000"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def validate_db_url(cls, v: Any) -> str:
        return sanitize_database_url(v)

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def validate_cors(cls, v: Any) -> List[str]:
        return parse_cors(v)

    @field_validator("WEBHOOK_BASE_URL", mode="before")
    @classmethod
    def validate_webhook_base_url(cls, v: Any) -> str:
        val = str(v).strip() if v else ""
        if not val or val == "http://localhost:8000":
            prod_url = os.getenv("VERCEL_PROJECT_PRODUCTION_URL") or os.getenv("VERCEL_URL")
            if prod_url:
                return f"https://{prod_url}"
            if os.getenv("VERCEL") or os.getenv("VERCEL_ENV"):
                return "https://darkrai-backend.vercel.app"
        return val or "http://localhost:8000"

    @field_validator("VERCEL", mode="before")
    @classmethod
    def validate_vercel(cls, v: Any) -> bool:
        if isinstance(v, str):
            if v.lower() in ("1", "true", "yes"):
                return True
            if not v.strip():
                return bool(os.getenv("VERCEL_ENV") or os.getenv("VERCEL_URL"))
        return bool(v)

settings = Settings(_env_file=".env")
