"""
Public-demo ledger packs (sandbox + tour).

No personal names, account masks, local haunts, or owner-only lifestyle trees.
Owner-only ensure (self-education name rule) must never be called from here.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from backend.schema.default_categories import (
    CAT_CRYPTO_FUND,
    CAT_INTERNAL,
    CAT_INSURANCE,
    CAT_SPOTIFY,
    CAT_TRANSFERS,
    DEFAULT_CATEGORIES,
    OWNER_LIFESTYLE_CATEGORY_IDS,
)
from backend.schema.models import (
    Account,
    AccountType,
    AssetClass,
    Category,
    CategoryRule,
    Institution,
    InvestmentEvent,
    InvestmentEventType,
    InvestmentLot,
    LotStatus,
    MatchField,
    MatchType,
    TradeSide,
    Transaction,
)
from backend.schema.seed_data import (
    ACC_ETORO,
    ACC_RB,
    ACC_REV_CRYPTO,
    ACC_REV_CZK,
    ACC_REV_STOCKS,
    ACC_REV_USD,
    RULE_DIGITAL_ASSETS,
    SEED_FX_RATES,
    SEED_SETTINGS,
    XFER_GROUP_REV_RB,
)
from backend.sheets.repository import SheetsRepository

UTC = timezone.utc
_TS = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)

def public_demo_categories() -> list[Category]:
    """Generic product tree without owner lifestyle branches."""
    return [c for c in DEFAULT_CATEGORIES if c.id not in OWNER_LIFESTYLE_CATEGORY_IDS]


# Synthetic institution accounts (no real masks / personal data)
DEMO_ACCOUNTS: list[Account] = [
    Account(
        id=ACC_RB,
        name="Demo Bank CZK",
        institution=Institution.RAIFFEISEN,
        account_type=AccountType.CHECKING,
        currency="CZK",
        account_number_mask="****0001/5500",
        is_active=True,
        created_at=_TS,
        updated_at=_TS,
    ),
    Account(
        id=ACC_REV_CZK,
        name="Demo Wallet CZK",
        institution=Institution.REVOLUT,
        account_type=AccountType.CHECKING,
        currency="CZK",
        is_active=True,
        created_at=_TS,
        updated_at=_TS,
    ),
    Account(
        id=ACC_REV_USD,
        name="Demo Wallet USD",
        institution=Institution.REVOLUT,
        account_type=AccountType.CHECKING,
        currency="USD",
        is_active=True,
        created_at=_TS,
        updated_at=_TS,
    ),
    Account(
        id=ACC_REV_STOCKS,
        name="Demo Stocks",
        institution=Institution.REVOLUT,
        account_type=AccountType.INVESTMENT,
        currency="USD",
        is_active=True,
        created_at=_TS,
        updated_at=_TS,
    ),
    Account(
        id=ACC_REV_CRYPTO,
        name="Demo Crypto",
        institution=Institution.REVOLUT,
        account_type=AccountType.CRYPTO,
        currency="USD",
        is_active=True,
        created_at=_TS,
        updated_at=_TS,
    ),
    Account(
        id=ACC_ETORO,
        name="Demo Broker",
        institution=Institution.ETORO,
        account_type=AccountType.INVESTMENT,
        currency="USD",
        is_active=True,
        created_at=_TS,
        updated_at=_TS,
    ),
]


DEMO_TOUR_RULES: list[CategoryRule] = [
    CategoryRule(
        id=RULE_DIGITAL_ASSETS,
        priority=6,
        match_field=MatchField.DESCRIPTION,
        match_type=MatchType.CONTAINS,
        match_value="Revolut Digital Assets Europe Ltd",
        category_id=CAT_CRYPTO_FUND,
        set_internal_transfer=True,
        institution_scope=None,
        is_active=True,
        notes="demo:digital_assets_crypto_pot",
        created_at=_TS,
        updated_at=_TS,
    ),
    CategoryRule(
        id=UUID("aa200001-0000-4000-8000-000000000001"),
        priority=10,
        match_field=MatchField.MERCHANT,
        match_type=MatchType.CONTAINS,
        match_value="Spotify",
        category_id=CAT_SPOTIFY,
        set_internal_transfer=False,
        institution_scope=None,
        is_active=True,
        notes="demo:streaming",
        created_at=_TS,
        updated_at=_TS,
    ),
    CategoryRule(
        id=UUID("aa200001-0000-4000-8000-000000000002"),
        priority=20,
        match_field=MatchField.ORIGINAL_DESCRIPTION,
        match_type=MatchType.CONTAINS,
        match_value="Sent from Revolut",
        category_id=CAT_INTERNAL,
        set_internal_transfer=True,
        institution_scope=Institution.RAIFFEISEN.value,
        is_active=True,
        notes="demo:internal_transfer_pair",
        created_at=_TS,
        updated_at=_TS,
    ),
    CategoryRule(
        id=UUID("aa200001-0000-4000-8000-000000000003"),
        priority=30,
        match_field=MatchField.MERCHANT,
        match_type=MatchType.CONTAINS,
        match_value="Allianz",
        category_id=CAT_INSURANCE,
        set_internal_transfer=False,
        institution_scope=None,
        is_active=True,
        notes="demo:insurance",
        created_at=_TS,
        updated_at=_TS,
    ),
    CategoryRule(
        id=UUID("aa200001-0000-4000-8000-000000000004"),
        priority=40,
        match_field=MatchField.DESCRIPTION,
        match_type=MatchType.STARTS_WITH,
        match_value="Transfer to",
        category_id=CAT_TRANSFERS,
        set_internal_transfer=False,
        institution_scope=Institution.REVOLUT.value,
        is_active=True,
        notes="demo:external_transfer_edge",
        created_at=_TS,
        updated_at=_TS,
    ),
]


DEMO_TOUR_TRANSACTIONS: list[Transaction] = [
    Transaction(
        id=UUID("22000001-0000-4000-8000-000000000001"),
        account_id=ACC_RB,
        booking_date=date(2026, 7, 28),
        value_date=date(2026, 7, 28),
        amount=Decimal("-185"),
        currency="CZK",
        amount_czk=Decimal("-185"),
        amount_usd=Decimal("-8.01"),
        fee_amount=Decimal("0"),
        fee_currency="CZK",
        merchant="Spotify",
        description="Card payment Spotify",
        original_description="Spotify · Demo City",
        source_institution=Institution.RAIFFEISEN.value,
        external_id="demo-tx-0001",
        category_id=CAT_SPOTIFY,
        is_internal_transfer=False,
        created_at=_TS,
        updated_at=_TS,
    ),
    Transaction(
        id=UUID("22000001-0000-4000-8000-000000000002"),
        account_id=ACC_RB,
        booking_date=date(2026, 7, 20),
        value_date=date(2026, 7, 20),
        amount=Decimal("-1887"),
        currency="CZK",
        amount_czk=Decimal("-1887"),
        amount_usd=Decimal("-81.69"),
        fee_amount=Decimal("0"),
        fee_currency="CZK",
        merchant="Allianz",
        description="Standing order Insurance premium",
        original_description="Insurance premium Allianz",
        source_institution=Institution.RAIFFEISEN.value,
        external_id="demo-tx-0002",
        category_id=CAT_INSURANCE,
        is_internal_transfer=False,
        created_at=_TS,
        updated_at=_TS,
    ),
    Transaction(
        id=UUID("22000001-0000-4000-8000-000000000003"),
        account_id=ACC_RB,
        booking_date=date(2026, 7, 20),
        value_date=date(2026, 7, 20),
        amount=Decimal("10000"),
        currency="CZK",
        amount_czk=Decimal("10000"),
        amount_usd=Decimal("432.90"),
        fee_amount=Decimal("0"),
        fee_currency="CZK",
        description="Incoming payment from wallet",
        original_description="Sent from Revolut",
        source_institution=Institution.RAIFFEISEN.value,
        external_id="demo-tx-0003",
        counterparty_name="Demo Wallet",
        category_id=CAT_INTERNAL,
        is_internal_transfer=True,
        transfer_group_id=XFER_GROUP_REV_RB,
        created_at=_TS,
        updated_at=_TS,
    ),
    Transaction(
        id=UUID("22000001-0000-4000-8000-000000000004"),
        account_id=ACC_REV_CZK,
        booking_date=date(2026, 7, 20),
        value_date=date(2026, 7, 20),
        amount=Decimal("-10000"),
        currency="CZK",
        amount_czk=Decimal("-10000"),
        amount_usd=Decimal("-432.90"),
        fee_amount=Decimal("0"),
        fee_currency="CZK",
        description="Transfer to own bank",
        original_description="Transfer to own bank account",
        source_institution=Institution.REVOLUT.value,
        external_id="demo-tx-0004",
        category_id=CAT_INTERNAL,
        is_internal_transfer=True,
        transfer_group_id=XFER_GROUP_REV_RB,
        created_at=_TS,
        updated_at=_TS,
    ),
    Transaction(
        id=UUID("22000001-0000-4000-8000-000000000005"),
        account_id=ACC_REV_CZK,
        booking_date=date(2026, 6, 15),
        value_date=date(2026, 6, 15),
        amount=Decimal("-890"),
        currency="CZK",
        amount_czk=Decimal("-890"),
        amount_usd=Decimal("-38.50"),
        fee_amount=Decimal("0"),
        fee_currency="CZK",
        merchant="Demo Cafe",
        description="Card Payment Demo Cafe",
        original_description="Demo Cafe · Sample Street",
        source_institution=Institution.REVOLUT.value,
        external_id="demo-tx-0005",
        created_at=_TS,
        updated_at=_TS,
    ),
]


LOT_DEMO_STOCK = UUID("23000001-0000-4000-8000-000000000001")
LOT_DEMO_ETF = UUID("23000001-0000-4000-8000-000000000002")
EVT_BUY_DEMO = UUID("24000001-0000-4000-8000-000000000001")
EVT_BUY_SAMPLE = UUID("24000001-0000-4000-8000-000000000002")

DEMO_TOUR_LOTS: list[InvestmentLot] = [
    InvestmentLot(
        id=LOT_DEMO_STOCK,
        account_id=ACC_REV_STOCKS,
        ticker="DEMO",
        asset_class=AssetClass.STOCK,
        source=Institution.REVOLUT.value,
        acquisition_date=date(2024, 1, 15),
        quantity_opened=Decimal("10"),
        quantity_remaining=Decimal("10"),
        cost_basis_native=Decimal("1000.00"),
        cost_basis_czk=Decimal("23000.00"),
        cost_basis_usd=Decimal("1000.00"),
        native_currency="USD",
        open_event_id=EVT_BUY_DEMO,
        status=LotStatus.OPEN,
        notes="demo synthetic lot",
        created_at=_TS,
        updated_at=_TS,
    ),
    InvestmentLot(
        id=LOT_DEMO_ETF,
        account_id=ACC_ETORO,
        ticker="SAMPLE",
        asset_class=AssetClass.STOCK,
        source=Institution.ETORO.value,
        acquisition_date=date(2025, 3, 1),
        quantity_opened=Decimal("5"),
        quantity_remaining=Decimal("5"),
        cost_basis_native=Decimal("500.00"),
        cost_basis_czk=Decimal("11500.00"),
        cost_basis_usd=Decimal("500.00"),
        native_currency="USD",
        open_event_id=EVT_BUY_SAMPLE,
        status=LotStatus.OPEN,
        notes="demo synthetic lot",
        created_at=_TS,
        updated_at=_TS,
    ),
]

DEMO_TOUR_EVENTS: list[InvestmentEvent] = [
    InvestmentEvent(
        id=EVT_BUY_DEMO,
        account_id=ACC_REV_STOCKS,
        event_type=InvestmentEventType.BUY,
        event_date=date(2024, 1, 15),
        ticker="DEMO",
        asset_class=AssetClass.STOCK,
        side=TradeSide.BUY,
        quantity=Decimal("10"),
        price_native=Decimal("100.00"),
        native_currency="USD",
        value_native=Decimal("1000.00"),
        value_usd=Decimal("1000.00"),
        value_czk=Decimal("23000.00"),
        lot_id=LOT_DEMO_STOCK,
        source=Institution.REVOLUT.value,
        external_id="demo-evt-0001",
        description="Demo buy DEMO",
        created_at=_TS,
        updated_at=_TS,
    ),
    InvestmentEvent(
        id=EVT_BUY_SAMPLE,
        account_id=ACC_ETORO,
        event_type=InvestmentEventType.BUY,
        event_date=date(2025, 3, 1),
        ticker="SAMPLE",
        asset_class=AssetClass.STOCK,
        side=TradeSide.BUY,
        quantity=Decimal("5"),
        price_native=Decimal("100.00"),
        native_currency="USD",
        value_native=Decimal("500.00"),
        value_usd=Decimal("500.00"),
        value_czk=Decimal("11500.00"),
        lot_id=LOT_DEMO_ETF,
        source=Institution.ETORO.value,
        external_id="demo-evt-0002",
        description="Demo buy SAMPLE",
        created_at=_TS,
        updated_at=_TS,
    ),
]


def ensure_public_demo_categories(repo: SheetsRepository) -> dict[str, int]:
    """
    Upsert public demo category tree + Digital Assets Europe rule only.

    Never installs personal self-education / name rules.
    Does not call ensure_defaults.ensure_digital_assets_rule (that pulls full
    DEFAULT_CATEGORIES including owner lifestyle branches).
    """
    existing = {
        c.id: c
        for c in repo.list_rows("Categories")
        if isinstance(c, Category)
    }
    to_write: list[Category] = []
    created = 0
    for template in public_demo_categories():
        if template.id not in existing:
            to_write.append(template)
            created += 1
    if to_write:
        repo.upsert_rows("Categories", to_write)

    # Digital Assets product rule only (domain non-negotiable for Revolut crypto).
    now = datetime.now(tz=UTC)
    rules = [
        r
        for r in repo.list_rows("CategoryRules")
        if isinstance(r, CategoryRule) and not getattr(r, "archived", False)
    ]
    has_da = any(
        "revolut digital assets europe" in (r.match_value or "").lower() for r in rules
    )
    if not has_da:
        repo.upsert_rows(
            "CategoryRules",
            [
                CategoryRule(
                    id=RULE_DIGITAL_ASSETS,
                    priority=6,
                    match_field=MatchField.DESCRIPTION,
                    match_type=MatchType.CONTAINS,
                    match_value="Revolut Digital Assets Europe Ltd",
                    category_id=CAT_CRYPTO_FUND,
                    set_internal_transfer=True,
                    institution_scope=None,
                    is_active=True,
                    notes="demo:digital_assets_crypto_pot",
                    created_at=now,
                    updated_at=now,
                )
            ],
        )
    return {"categories_created": created, "total": len(public_demo_categories())}


def seed_public_minimal(repo: SheetsRepository) -> None:
    """Accounts + public categories/rules/FX/settings for demos (no personal data)."""
    if not repo.list_rows("Accounts"):
        repo.upsert_rows("Accounts", DEMO_ACCOUNTS)
    ensure_public_demo_categories(repo)
    existing_rules = repo.list_rows("CategoryRules")
    if not existing_rules:
        repo.upsert_rows("CategoryRules", DEMO_TOUR_RULES)
    else:
        # Ensure demo rules exist without wiping user-added sandbox rules
        have = {
            r.id
            for r in existing_rules
            if isinstance(r, CategoryRule)
        }
        missing = [r for r in DEMO_TOUR_RULES if r.id not in have]
        if missing:
            repo.upsert_rows("CategoryRules", missing)
    if not repo.list_rows("FXRates"):
        repo.upsert_rows("FXRates", SEED_FX_RATES)
    if not repo.list_rows("Settings"):
        repo.upsert_rows("Settings", SEED_SETTINGS)


def seed_public_tour(repo: SheetsRepository) -> None:
    """Full synthetic sample portfolio for Explore sample portfolio."""
    seed_public_minimal(repo)
    if not repo.list_rows("Transactions"):
        repo.upsert_rows("Transactions", DEMO_TOUR_TRANSACTIONS)
    if DEMO_TOUR_LOTS and not repo.list_rows("InvestmentLots"):
        try:
            repo.upsert_rows("InvestmentLots", DEMO_TOUR_LOTS)
        except Exception:  # noqa: BLE001
            pass
    if DEMO_TOUR_EVENTS and not repo.list_rows("InvestmentEvents"):
        try:
            repo.upsert_rows("InvestmentEvents", DEMO_TOUR_EVENTS)
        except Exception:  # noqa: BLE001
            pass


def ledger_contains_personal_residue(repo: SheetsRepository) -> list[str]:
    """Test helper: list residue markers if any (empty = clean)."""
    hits: list[str] = []
    banned = (
        "CEZARY BIERNAT",
        "Cezary Biernat",
        "2489943002",
        "Bad Jeffs",
        "Biernat",
    )
    for tab in ("CategoryRules", "Transactions", "Accounts"):
        try:
            rows = repo.list_rows(tab)
        except Exception:  # noqa: BLE001
            continue
        blob = " ".join(str(r) for r in rows)
        for b in banned:
            if b in blob:
                hits.append(f"{tab}:{b}")
    return hits
