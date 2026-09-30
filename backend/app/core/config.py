"""Application settings — everything comes from environment variables."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- app ---
    app_env: str = "development"  # development | test | production
    app_name: str = "Eitaa Support Desk"
    api_prefix: str = "/api/v1"

    # --- secrets ---
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    jwt_secret: str = ""  # falls back to secret_key when empty
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    # --- database ---
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/eitaa_desk"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False

    # --- cors / security ---
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_upload_size_mb: int = 25
    allowed_upload_extensions: str = (
        "png,jpg,jpeg,gif,webp,mp3,ogg,oga,opus,wav,m4a,mp4,webm,mov,"
        "pdf,doc,docx,xls,xlsx,ppt,pptx,txt,csv,zip,rar,7z,json"
    )
    rate_limit_per_minute: int = 300
    rate_limit_auth_per_minute: int = 10
    trusted_host: str = ""  # optional Host header allowlist (comma separated)

    # --- eitaa ---
    eitaa_session_encryption_key: str = ""  # Fernet key (python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    eitaa_sync_interval: int = 15  # seconds between sync passes
    eitaa_sync_enabled: bool = True
    eitaa_sync_dialog_limit: int = 100
    eitaa_sync_history_limit: int = 50
    eitaa_sync_kinds: str = "private"  # dialog kinds to import: private,group,supergroup,channel
    eitaa_api_timeout: float = 45.0

    # --- workers ---
    run_sync_worker: bool = True
    run_notification_worker: bool = True
    notification_unanswered_after_seconds: int = 600  # 10 minutes
    notification_worker_interval: int = 60

    # --- storage ---
    uploads_dir: str = "/data/uploads"

    # --- logging ---
    log_level: str = "INFO"
    log_json: bool = False

    # --- bootstrap owner (used once, when the users table is empty) ---
    bootstrap_owner_email: str = ""
    bootstrap_owner_password: str = ""
    bootstrap_owner_name: str = "Owner"

    # --- optional redis (rate limiting backend when set) ---
    redis_url: str = ""

    # ------------------------------------------------------------------ helpers
    @property
    def effective_jwt_secret(self) -> str:
        return self.jwt_secret or self.secret_key

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_extension_list(self) -> set[str]:
        return {
            e.strip().lower().lstrip(".")
            for e in self.allowed_upload_extensions.split(",")
            if e.strip()
        }

    @property
    def sync_kind_list(self) -> set[str]:
        kinds = {k.strip().lower() for k in self.eitaa_sync_kinds.split(",") if k.strip()}
        valid = {"private", "group", "supergroup", "channel"}
        return kinds & valid or {"private"}

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def uploads_path(self) -> Path:
        return Path(self.uploads_dir)

    @field_validator("app_env")
    @classmethod
    def _validate_env(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in {"development", "test", "production"}:
            raise ValueError("APP_ENV must be development|test|production")
        return v

    def validate_production_secrets(self) -> list[str]:
        """Return a list of fatal production misconfigurations (empty = OK)."""
        problems: list[str] = []
        if self.is_production:
            if len(self.secret_key) < 32:
                problems.append("SECRET_KEY must be at least 32 characters in production")
            if not self.jwt_secret or len(self.jwt_secret) < 32:
                problems.append("JWT_SECRET must be set (>= 32 chars) in production")
            if not self.eitaa_session_encryption_key:
                problems.append("EITAA_SESSION_ENCRYPTION_KEY must be set in production")
        if not self.eitaa_session_encryption_key:
            # dev fallback key so local runs work; production requires the real one
            pass
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
