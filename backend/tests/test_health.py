"""Health endpoint and config defaults."""

from __future__ import annotations

from backend.config import Settings


def test_health_ok(client) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["app"] == "Gauntlet Finance API"
    assert "auth_mode" in body
    assert body["spreadsheet_configured"] is False


def test_settings_defaults_from_class() -> None:
    """Field defaults match Gauntlet product constraints."""
    fields = Settings.model_fields
    assert fields["api_port"].default == 8020
    assert fields["session_cookie_name"].default == "gf_session"
    assert fields["holding_period_exemption_days"].default == 1095
    assert fields["primary_display_currency"].default == "USD"
    assert fields["secondary_display_currency"].default == "CZK"
    assert "5190" in str(fields["cors_origins"].default)
