"""Application settings (env / .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = parent of backend/
_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Known-insecure defaults — refuse these in production (especially multi-tenant).
INSECURE_SECRET_DEFAULTS = frozenset(
    {
        "",
        "dev-change-me-use-long-random-string",
        "change-me",
        "secret",
        "test-secret",
    }
)


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

    # Demo password login (legacy landing form). Prefer one-click sandbox/tour.
    demo_login_enabled: bool = False  # env DEMO_LOGIN_ENABLED
    demo_email: str = "demo@gauntlet.local"  # env DEMO_EMAIL
    demo_password: str = ""  # env DEMO_PASSWORD — e.g. "demo"; never commit real secrets

    # Public one-click demos (no email/password). Off by default.
    demo_sandbox_enabled: bool = False  # env DEMO_SANDBOX_ENABLED — empty ephemeral ledger
    demo_tour_enabled: bool = False  # env DEMO_TOUR_ENABLED — synthetic read-only sample
    demo_sandbox_max_active: int = 50  # env DEMO_SANDBOX_MAX_ACTIVE

    # Owner password login (real ledger). Use when ALLOW_OPEN_AUTH=false on public hosts.
    owner_email: str = ""  # env OWNER_EMAIL — shown on landing; must match login email
    owner_password: str = ""  # env OWNER_PASSWORD — long secret; never commit

    # Grok / SpaceXAI (server-side only; never expose to browser)
    # AI_ENABLED must be true AND XAI_API_KEY set for platform suggestions.
    ai_enabled: bool = False  # env AI_ENABLED
    xai_api_key: str = ""  # env XAI_API_KEY
    xai_base_url: str = "https://api.x.ai/v1"  # env XAI_BASE_URL
    ai_model: str = "grok-4.3"  # env AI_MODEL
    ai_daily_token_cap: int = 200_000  # env AI_DAILY_TOKEN_CAP — per principal
    ai_global_daily_token_cap: int = 2_000_000  # env AI_GLOBAL_DAILY_TOKEN_CAP
    ai_max_merchants_per_request: int = 40  # env AI_MAX_MERCHANTS_PER_REQUEST
    ai_request_timeout_seconds: float = 60.0  # env AI_REQUEST_TIMEOUT_SECONDS
    # Writable public sandbox: if no XAI key, use deterministic heuristics so demos work.
    ai_sandbox_fallback: bool = True  # env AI_SANDBOX_FALLBACK

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

    @property
    def secret_key_is_insecure(self) -> bool:
        key = (self.secret_key or "").strip()
        if key in INSECURE_SECRET_DEFAULTS:
            return True
        if len(key) < 16:
            return True
        return False

    @property
    def effective_debug(self) -> bool:
        """Never enable debug exception bodies in production."""
        if self.is_production:
            return False
        return self.debug

    @property
    def ai_configured(self) -> bool:
        """Kill switch + platform key present (testing / platform-paid path)."""
        return bool(self.ai_enabled and (self.xai_api_key or "").strip())

    def ai_available_for_sandbox(self) -> bool:
        """Sandbox may use real Grok or local fallback heuristics."""
        if self.ai_configured:
            return True
        return bool(self.ai_sandbox_fallback)


def validate_settings_for_boot(settings: Settings | None = None) -> None:
    """
    Hard-fail unsafe production configuration.

    Raises RuntimeError so process exit is clear on misconfigured public hosts.
    """
    settings = settings or get_settings()
    if not settings.is_production:
        return
    if settings.secret_key_is_insecure:
        raise RuntimeError(
            "Refusing to start: SECRET_KEY is missing, too short (<16), or a known "
            "insecure default. Set a long random SECRET_KEY in production."
        )
    if settings.multi_tenant and settings.auth_mode in {"dev", "disabled"}:
        raise RuntimeError(
            "Refusing to start: MULTI_TENANT=true requires AUTH_MODE=oauth in production."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
