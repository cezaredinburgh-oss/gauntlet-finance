"""Application settings (env / .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = parent of backend/
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Gauntlet Finance API"
    app_env: Literal["development", "production", "test"] = "development"
    debug: bool = True

    # Server — Gauntlet defaults avoid Collective 8000/8010 and common Vite 5173/5180
    api_host: str = "127.0.0.1"
    api_port: int = 8020
    cors_origins: str = (
        "http://localhost:5190,http://127.0.0.1:5190"
    )

    # Auth
    # - dev: no browser login; uses service account for Sheets when SPREADSHEET_ID set
    # - oauth: Google user login (browser) for Sheets access
    # - disabled: no auth checks (still needs credentials for Sheets)
    # Production refuses auth_mode=dev/disabled unless ALLOW_OPEN_AUTH=true.
    auth_mode: Literal["oauth", "dev", "disabled"] = "dev"
    allow_open_auth: bool = False  # env ALLOW_OPEN_AUTH — required for open auth in production
    allow_setup_wizard: bool = False  # env ALLOW_SETUP_WIZARD — re-enable wizard when sheet configured
    setup_token: str = ""  # env SETUP_TOKEN — optional X-Setup-Token for wizard write APIs
    secret_key: str = Field(default="dev-change-me-use-long-random-string")
    google_client_id: str = ""
    google_client_secret: str = ""
    oauth_redirect_uri: str = "http://localhost:8020/api/auth/callback"
    session_cookie_name: str = "gf_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 7

    # Google Sheets
    spreadsheet_id: str = ""
    google_application_credentials: str = "secrets/service-account.json"
    google_service_account_json: str = ""

    # Optional hard-exit when Sheets unconfigured (default: always start; health flag)
    require_sheets: bool = False

    # Prices
    price_cache_ttl_seconds: int = 60
    price_history_cache_ttl_seconds: int = 3600
    price_history_intraday_cache_ttl_seconds: int = 90
    yfinance_enabled: bool = True

    # Domain defaults
    holding_period_exemption_days: int = 1095
    primary_display_currency: str = "USD"
    secondary_display_currency: str = "CZK"
    # Naive statement clocks (Revolut CSV has no TZ) — matches seed Settings.timezone
    statement_timezone: str = "Europe/Prague"

    # Cron / background jobs (optional)
    cron_secret: str = ""

    # Multi-tenant SaaS (invite-only OAuth + one Google Sheet per user)
    multi_tenant: bool = False  # env MULTI_TENANT
    control_db_path: str = ""  # env CONTROL_DB_PATH — default data/gauntlet_control.db
    platform_admin_emails: str = ""  # env PLATFORM_ADMIN_EMAILS — comma-separated
    # When multi_tenant and no real Sheets: assign memory spreadsheet ids (tests / local)
    multi_tenant_memory_sheets: bool = False  # env MULTI_TENANT_MEMORY_SHEETS

    @field_validator("spreadsheet_id", mode="before")
    @classmethod
    def strip_spreadsheet_id(cls, v: object) -> object:
        if isinstance(v, str):
            s = v.strip()
            if "/d/" in s:
                try:
                    s = s.split("/d/")[1].split("/")[0]
                except IndexError:
                    pass
            return s
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def spreadsheet_configured(self) -> bool:
        return bool(self.spreadsheet_id)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def open_auth_permitted(self) -> bool:
        """
        Whether unauthenticated open access (auth_mode dev/disabled) is allowed.

        True when:
        - auth_mode is not open (e.g. oauth), or
        - ALLOW_OPEN_AUTH=true, or
        - APP_ENV is development/test (local and pytest).

        Multi-tenant production never permits open auth (AC1).
        """
        if self.multi_tenant and self.is_production:
            return False
        if self.auth_mode not in {"dev", "disabled"}:
            return True
        if self.allow_open_auth:
            return True
        if self.app_env in {"development", "test"}:
            return True
        return False


@lru_cache
def get_settings() -> Settings:
    return Settings()
