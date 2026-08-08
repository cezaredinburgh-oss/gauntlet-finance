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


def seed_minimal(repo: SheetsRepository) -> None:
    """Ensure basic accounts + category rules exist for uploads."""
    existing_acc = repo.list_rows("Accounts")
    if not existing_acc:
        repo.upsert_rows("Accounts", seed.SEED_ACCOUNTS)
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
    seed_minimal(repo)
    if not repo.list_rows("Transactions"):
        repo.upsert_rows("Transactions", seed.SEED_TRANSACTIONS)
    if not repo.list_rows("InvestmentLots"):
        repo.upsert_rows("InvestmentLots", seed.SEED_INVESTMENT_LOTS)
    if not repo.list_rows("InvestmentEvents"):
        repo.upsert_rows("InvestmentEvents", seed.SEED_INVESTMENT_EVENTS)
