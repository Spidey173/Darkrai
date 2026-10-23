import ast
import json
import os
import re
from typing import Any, List, Union, Optional
from pydantic import field_validator, model_validator
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

DEV_FALLBACK_SECRET_KEY = "darkrai-dev-secret-key-32bytes-for-development"
DEV_FALLBACK_ENCRYPTION_KEY = "DgMHhFBzYTgCBS_Y9pSwCl5_ObmQUmD1i528mpYdPTQ="
INSECURE_SECRET_KEYS = {
    "change_me_to_a_secure_random_string",
    "secret",
    "password",
    ""
}
INSECURE_ENCRYPTION_KEYS = {
    "change_me_to_32_urlsafe_base64_encoded_bytes=",
    ""
}

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
    TESTING: bool = False

    # Security Config (defaults resolved safely in model_validator based on APP_ENV)
    SECRET_KEY: str = ""
    ENCRYPTION_KEY: str = ""

    # Database config (defaults to local aiosqlite for zero-config startup and test isolation)
    DATABASE_URL: str = "sqlite+aiosqlite:///./darkrai.db"

    # Serverless runtime detection (Vercel sets VERCEL=1)
    VERCEL: bool = False

    # Execution mode configuration
    EXECUTE_INLINE: bool = False
    FRONTEND_URL: Optional[str] = None
    MAX_WEBHOOK_PAYLOAD_BYTES: int = 2 * 1024 * 1024  # 2MB request limit

    # Redis Queue config (defaults to standard Redis URL, with resilient async in-memory fallback)
    REDIS_URL: str = "redis://localhost:6379/0"
    USE_REDIS_QUEUE: bool = True
    MAX_EVENT_RETRIES: int = 3

    BACKEND_CORS_ORIGINS: Union[str, List[str]] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://darkrai17.vercel.app"
    ]

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

    @model_validator(mode="after")
    def validate_security_credentials(self) -> "Settings":
        env = (self.APP_ENV or "development").lower()
        is_dev = env in ("development", "dev", "test", "testing", "local")

        # Validate SECRET_KEY
        if not self.SECRET_KEY or self.SECRET_KEY in INSECURE_SECRET_KEYS:
            if is_dev:
                self.SECRET_KEY = DEV_FALLBACK_SECRET_KEY
            else:
                raise ValueError(
                    "Production startup aborted: SECRET_KEY is missing or using an insecure default. "
                    "Set a cryptographically strong SECRET_KEY (min 32 characters) in production."
                )
        elif len(self.SECRET_KEY) < 32 and not is_dev:
            raise ValueError(
                "Production startup aborted: SECRET_KEY must be at least 32 characters long."
            )

        # Validate ENCRYPTION_KEY
        if not self.ENCRYPTION_KEY or self.ENCRYPTION_KEY in INSECURE_ENCRYPTION_KEYS:
            if is_dev:
                self.ENCRYPTION_KEY = DEV_FALLBACK_ENCRYPTION_KEY
            else:
                raise ValueError(
                    "Production startup aborted: ENCRYPTION_KEY is missing or using an insecure default. "
                    "Set a 32-byte url-safe base64-encoded Fernet key in production."
                )

        # Validate Fernet key format
        try:
            from cryptography.fernet import Fernet
            Fernet(self.ENCRYPTION_KEY.encode("utf-8"))
        except Exception as e:
            if is_dev:
                self.ENCRYPTION_KEY = DEV_FALLBACK_ENCRYPTION_KEY
            else:
                raise ValueError(f"Production startup aborted: Invalid ENCRYPTION_KEY for Fernet cipher: {e}")

        if self.VERCEL:
            self.EXECUTE_INLINE = True

        return self

settings = Settings(_env_file=".env")

