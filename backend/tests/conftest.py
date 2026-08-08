"""Pytest fixtures for Gauntlet backend."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def _test_env() -> None:
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("AUTH_MODE", "disabled")
    os.environ.setdefault("SPREADSHEET_ID", "")
    # Ensure settings re-read env after tests set keys
    from backend.config import get_settings

    get_settings.cache_clear()


@pytest.fixture()
def client() -> TestClient:
    from backend.config import get_settings
    from backend.api.main import create_app

    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as c:
        yield c
