"""Seed Accounts, Categories, CategoryRules into a repository (dev helper)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from backend.schema.models import (
    Account,
    AccountType,
    Category,
    CategoryRule,
    Institution,
    LifeDomain,
    MatchField,
    MatchType,
    Necessity,
)
from backend.schema import seed_data as seed
from backend.sheets.repository import SheetsRepository

TS = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)


def seed_minimal(repo: SheetsRepository, *, public_demo: bool = False) -> None:
    """
    Ensure basic accounts + category rules exist for uploads.

    public_demo=True: synthetic accounts + public category pack (no personal residue).
    """
    if public_demo:
        from backend.schema.demo_public import seed_public_minimal

        seed_public_minimal(repo)
        return

    existing_acc = repo.list_rows("Accounts")
    if not existing_acc:
        # Prefer synthetic demo accounts for empty ledgers (safer if ever public).
        from backend.schema.demo_public import DEMO_ACCOUNTS

        repo.upsert_rows("Accounts", DEMO_ACCOUNTS)
    existing_cat = repo.list_rows("Categories")
    if not existing_cat:
        repo.upsert_rows("Categories", seed.SEED_CATEGORIES)
        repo.upsert_rows("CategoryRules", seed.SEED_CATEGORY_RULES)
    existing_fx = repo.list_rows("FXRates")
    if not existing_fx:
        repo.upsert_rows("FXRates", seed.SEED_FX_RATES)
    existing_set = repo.list_rows("Settings")
    if not existing_set:
        repo.upsert_rows("Settings", seed.SEED_SETTINGS)


def seed_full_demo(repo: SheetsRepository) -> None:
    """Public tour portfolio — fully synthetic (see schema/demo_public.py)."""
    from backend.schema.demo_public import seed_public_tour

    seed_public_tour(repo)
