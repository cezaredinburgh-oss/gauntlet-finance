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
    CAT_BANK_FEES,
    CAT_BROKER,
    CAT_CASH_WITHDRAWAL,
    CAT_CLOTHING,
    CAT_COFFEE,
    CAT_CRYPTO_FUND,
    CAT_ELECTRONICS,
    CAT_EXTERNAL_XFER,
    CAT_FUEL_CAR,
    CAT_GOING_OUT,
    CAT_GROCERIES,
    CAT_INSURANCE,
    CAT_INTERNAL,
    CAT_INTERNET,
    CAT_OTHER_INCOME,
    CAT_PHARMACY,
    CAT_PUBLIC_TRANSIT,
    CAT_RENT,
    CAT_RESTAURANTS,
    CAT_SALARY,
    CAT_SHOP_GENERAL,
    CAT_SOFTWARE,
    CAT_SPOTIFY,
    CAT_STREAMING,
    CAT_TAXI,
    CAT_TRANSFERS,
    CAT_UTILITIES,
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
    ParserKey,
    StatementFile,
    StatementFileStatus,
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


# Real institution display names (synthetic account masks only — no personal numbers)
DEMO_ACCOUNTS: list[Account] = [
    Account(
        id=ACC_RB,
        name="Raiffeisen CZK",
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
        name="Revolut CZK",
        institution=Institution.REVOLUT,
        account_type=AccountType.CHECKING,
        currency="CZK",
        is_active=True,
        created_at=_TS,
        updated_at=_TS,
    ),
    Account(
        id=ACC_REV_USD,
        name="Revolut USD",
        institution=Institution.REVOLUT,
        account_type=AccountType.CHECKING,
        currency="USD",
        is_active=True,
        created_at=_TS,
        updated_at=_TS,
    ),
    Account(
        id=ACC_REV_STOCKS,
        name="Revolut Stocks",
        institution=Institution.REVOLUT,
        account_type=AccountType.INVESTMENT,
        currency="USD",
        is_active=True,
        created_at=_TS,
        updated_at=_TS,
    ),
    Account(
        id=ACC_REV_CRYPTO,
        name="Revolut Crypto",
        institution=Institution.REVOLUT,
        account_type=AccountType.CRYPTO,
        currency="USD",
        is_active=True,
        created_at=_TS,
        updated_at=_TS,
    ),
    Account(
        id=ACC_ETORO,
        name="eToro",
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


# Illustrative FX for demo amounts (not live market data).
_USD_CZK = Decimal("23.10")
_TOUR_TX_MIN = 40  # upgrade sparse tour seeds below this count


def _tx_id(n: int) -> UUID:
    return UUID(f"22000001-0000-4000-8000-{n:012d}")


def _evt_id(n: int) -> UUID:
    return UUID(f"24000001-0000-4000-8000-{n:012d}")


def _lot_id(n: int) -> UUID:
    return UUID(f"23000001-0000-4000-8000-{n:012d}")


def _file_id(n: int) -> UUID:
    return UUID(f"25000001-0000-4000-8000-{n:012d}")


def _hash(n: int) -> str:
    return f"{n:064x}"


def _money(amount: Decimal, currency: str) -> tuple[Decimal, Decimal]:
    """Return (amount_czk, amount_usd) for a signed amount."""
    if currency == "CZK":
        return amount, (amount / _USD_CZK).quantize(Decimal("0.01"))
    return (amount * _USD_CZK).quantize(Decimal("0.01")), amount


def _tx(
    n: int,
    *,
    account_id: UUID,
    day: date,
    amount: str,
    currency: str,
    institution: Institution,
    merchant: str | None = None,
    description: str = "",
    original_description: str | None = None,
    category_id: UUID | None = None,
    is_internal: bool = False,
    transfer_group_id: UUID | None = None,
    counterparty_name: str | None = None,
    source_file_id: UUID | None = None,
    original_file_hash: str | None = None,
) -> Transaction:
    amt = Decimal(amount)
    czk, usd = _money(amt, currency)
    desc = description or (merchant or "Demo transaction")
    return Transaction(
        id=_tx_id(n),
        account_id=account_id,
        booking_date=day,
        value_date=day,
        amount=amt,
        currency=currency,
        amount_czk=czk,
        amount_usd=usd,
        fee_amount=Decimal("0"),
        fee_currency=currency,
        merchant=merchant,
        description=desc,
        original_description=original_description or desc,
        source_institution=institution.value,
        external_id=f"demo-tx-{n:04d}",
        counterparty_name=counterparty_name,
        category_id=category_id,
        is_internal_transfer=is_internal,
        transfer_group_id=transfer_group_id,
        source_file_id=source_file_id,
        original_file_hash=original_file_hash,
        created_at=_TS,
        updated_at=_TS,
    )


def _build_tour_transactions() -> list[Transaction]:
    """Rich multi-bank synthetic spend/income for Home, Spending, Transactions."""
    f_rb, f_rev, f_stk = _file_id(1), _file_id(2), _file_id(3)
    h_rb, h_rev, h_stk = _hash(1), _hash(2), _hash(3)
    rows: list[Transaction] = []
    n = 1

    def add(**kwargs: object) -> None:
        nonlocal n
        rows.append(_tx(n, **kwargs))  # type: ignore[arg-type]
        n += 1

    # --- Monthly salary + rent (Raiffeisen checking) Mar–Aug 2026 ---
    for month in range(3, 9):
        add(
            account_id=ACC_RB,
            day=date(2026, month, 1),
            amount="85000",
            currency="CZK",
            institution=Institution.RAIFFEISEN,
            merchant="Demo Employer a.s.",
            description="Salary payment",
            category_id=CAT_SALARY,
            source_file_id=f_rb,
            original_file_hash=h_rb,
        )
        add(
            account_id=ACC_RB,
            day=date(2026, month, 2),
            amount="-24500",
            currency="CZK",
            institution=Institution.RAIFFEISEN,
            merchant="Demo Housing s.r.o.",
            description="Standing order Rent",
            category_id=CAT_RENT,
            source_file_id=f_rb,
            original_file_hash=h_rb,
        )
        add(
            account_id=ACC_RB,
            day=date(2026, month, 5),
            amount="-1890",
            currency="CZK",
            institution=Institution.RAIFFEISEN,
            merchant="Demo Energy",
            description="Utilities",
            category_id=CAT_UTILITIES,
            source_file_id=f_rb,
            original_file_hash=h_rb,
        )
        add(
            account_id=ACC_RB,
            day=date(2026, month, 6),
            amount="-699",
            currency="CZK",
            institution=Institution.RAIFFEISEN,
            merchant="Demo Mobile",
            description="Internet / phone",
            category_id=CAT_INTERNET,
            source_file_id=f_rb,
            original_file_hash=h_rb,
        )
        add(
            account_id=ACC_RB,
            day=date(2026, month, 8),
            amount="-1887",
            currency="CZK",
            institution=Institution.RAIFFEISEN,
            merchant="Allianz",
            description="Insurance premium",
            category_id=CAT_INSURANCE,
            source_file_id=f_rb,
            original_file_hash=h_rb,
        )

    # --- Groceries & everyday (mix banks) ---
    grocery = [
        (3, 4, "-1250", "Demo Market", ACC_RB, Institution.RAIFFEISEN),
        (3, 11, "-980", "Demo Fresh", ACC_REV_CZK, Institution.REVOLUT),
        (3, 18, "-1420", "Demo Market", ACC_RB, Institution.RAIFFEISEN),
        (3, 25, "-760", "Demo Corner Shop", ACC_REV_CZK, Institution.REVOLUT),
        (4, 3, "-1100", "Demo Market", ACC_RB, Institution.RAIFFEISEN),
        (4, 10, "-890", "Demo Fresh", ACC_REV_CZK, Institution.REVOLUT),
        (4, 17, "-1340", "Demo Market", ACC_RB, Institution.RAIFFEISEN),
        (4, 24, "-720", "Demo Corner Shop", ACC_REV_CZK, Institution.REVOLUT),
        (5, 2, "-1180", "Demo Market", ACC_RB, Institution.RAIFFEISEN),
        (5, 9, "-950", "Demo Fresh", ACC_REV_CZK, Institution.REVOLUT),
        (5, 16, "-1290", "Demo Market", ACC_RB, Institution.RAIFFEISEN),
        (5, 23, "-810", "Demo Corner Shop", ACC_REV_CZK, Institution.REVOLUT),
        (6, 6, "-1400", "Demo Market", ACC_RB, Institution.RAIFFEISEN),
        (6, 13, "-870", "Demo Fresh", ACC_REV_CZK, Institution.REVOLUT),
        (6, 20, "-1210", "Demo Market", ACC_RB, Institution.RAIFFEISEN),
        (6, 27, "-990", "Demo Corner Shop", ACC_REV_CZK, Institution.REVOLUT),
        (7, 4, "-1350", "Demo Market", ACC_RB, Institution.RAIFFEISEN),
        (7, 11, "-920", "Demo Fresh", ACC_REV_CZK, Institution.REVOLUT),
        (7, 18, "-1480", "Demo Market", ACC_RB, Institution.RAIFFEISEN),
        (7, 25, "-780", "Demo Corner Shop", ACC_REV_CZK, Institution.REVOLUT),
        (8, 1, "-1300", "Demo Market", ACC_RB, Institution.RAIFFEISEN),
        (8, 8, "-860", "Demo Fresh", ACC_REV_CZK, Institution.REVOLUT),
    ]
    for mo, day, amt, merch, acc, inst in grocery:
        add(
            account_id=acc,
            day=date(2026, mo, day),
            amount=amt,
            currency="CZK",
            institution=inst,
            merchant=merch,
            description=f"Card payment {merch}",
            category_id=CAT_GROCERIES,
            source_file_id=f_rb if inst == Institution.RAIFFEISEN else f_rev,
            original_file_hash=h_rb if inst == Institution.RAIFFEISEN else h_rev,
        )

    # --- Coffee / restaurants / going out ---
    lifestyle = [
        (3, 7, "-95", "Demo Cafe", CAT_COFFEE, ACC_REV_CZK),
        (3, 14, "-420", "Demo Bistro", CAT_RESTAURANTS, ACC_REV_CZK),
        (3, 21, "-680", "Demo Cinema", CAT_GOING_OUT, ACC_RB),
        (4, 5, "-110", "Demo Cafe", CAT_COFFEE, ACC_REV_CZK),
        (4, 12, "-890", "Demo Kitchen", CAT_RESTAURANTS, ACC_REV_CZK),
        (4, 19, "-350", "Demo Bar", CAT_GOING_OUT, ACC_REV_CZK),
        (5, 3, "-85", "Demo Cafe", CAT_COFFEE, ACC_REV_CZK),
        (5, 10, "-560", "Demo Bistro", CAT_RESTAURANTS, ACC_RB),
        (5, 24, "-1200", "Demo Night Out", CAT_GOING_OUT, ACC_REV_CZK),
        (6, 8, "-100", "Demo Cafe", CAT_COFFEE, ACC_REV_CZK),
        (6, 15, "-740", "Demo Kitchen", CAT_RESTAURANTS, ACC_REV_CZK),
        (6, 22, "-450", "Demo Cinema", CAT_GOING_OUT, ACC_RB),
        (7, 5, "-90", "Demo Cafe", CAT_COFFEE, ACC_REV_CZK),
        (7, 12, "-610", "Demo Bistro", CAT_RESTAURANTS, ACC_REV_CZK),
        (7, 26, "-980", "Demo Night Out", CAT_GOING_OUT, ACC_REV_CZK),
        (8, 2, "-105", "Demo Cafe", CAT_COFFEE, ACC_REV_CZK),
        (8, 9, "-530", "Demo Kitchen", CAT_RESTAURANTS, ACC_RB),
    ]
    for mo, day, amt, merch, cat, acc in lifestyle:
        add(
            account_id=acc,
            day=date(2026, mo, day),
            amount=amt,
            currency="CZK",
            institution=Institution.REVOLUT if acc == ACC_REV_CZK else Institution.RAIFFEISEN,
            merchant=merch,
            description=f"Card payment {merch}",
            category_id=cat,
            source_file_id=f_rev if acc == ACC_REV_CZK else f_rb,
            original_file_hash=h_rev if acc == ACC_REV_CZK else h_rb,
        )

    # --- Subscriptions ---
    for month in range(3, 9):
        add(
            account_id=ACC_RB,
            day=date(2026, month, 12),
            amount="-185",
            currency="CZK",
            institution=Institution.RAIFFEISEN,
            merchant="Spotify",
            description="Card payment Spotify",
            original_description="Spotify · Demo City",
            category_id=CAT_SPOTIFY,
            source_file_id=f_rb,
            original_file_hash=h_rb,
        )
        add(
            account_id=ACC_REV_USD,
            day=date(2026, month, 14),
            amount="-15.99",
            currency="USD",
            institution=Institution.REVOLUT,
            merchant="Netflix",
            description="Netflix subscription",
            category_id=CAT_STREAMING,
            source_file_id=f_rev,
            original_file_hash=h_rev,
        )
        add(
            account_id=ACC_REV_USD,
            day=date(2026, month, 15),
            amount="-10.00",
            currency="USD",
            institution=Institution.REVOLUT,
            merchant="GitHub",
            description="Software subscription",
            category_id=CAT_SOFTWARE,
            source_file_id=f_rev,
            original_file_hash=h_rev,
        )

    # --- Transport ---
    transport = [
        (3, 9, "-450", "Demo Fuel", CAT_FUEL_CAR, ACC_RB, Institution.RAIFFEISEN),
        (3, 16, "-32", "Demo Transit", CAT_PUBLIC_TRANSIT, ACC_REV_CZK, Institution.REVOLUT),
        (4, 8, "-520", "Demo Fuel", CAT_FUEL_CAR, ACC_RB, Institution.RAIFFEISEN),
        (4, 22, "-180", "Demo Ride", CAT_TAXI, ACC_REV_CZK, Institution.REVOLUT),
        (5, 7, "-480", "Demo Fuel", CAT_FUEL_CAR, ACC_RB, Institution.RAIFFEISEN),
        (5, 18, "-28", "Demo Transit", CAT_PUBLIC_TRANSIT, ACC_REV_CZK, Institution.REVOLUT),
        (6, 11, "-510", "Demo Fuel", CAT_FUEL_CAR, ACC_RB, Institution.RAIFFEISEN),
        (6, 28, "-220", "Demo Ride", CAT_TAXI, ACC_REV_CZK, Institution.REVOLUT),
        (7, 9, "-495", "Demo Fuel", CAT_FUEL_CAR, ACC_RB, Institution.RAIFFEISEN),
        (7, 20, "-35", "Demo Transit", CAT_PUBLIC_TRANSIT, ACC_REV_CZK, Institution.REVOLUT),
        (8, 6, "-530", "Demo Fuel", CAT_FUEL_CAR, ACC_RB, Institution.RAIFFEISEN),
    ]
    for mo, day, amt, merch, cat, acc, inst in transport:
        add(
            account_id=acc,
            day=date(2026, mo, day),
            amount=amt,
            currency="CZK",
            institution=inst,
            merchant=merch,
            description=f"Card payment {merch}",
            category_id=cat,
            source_file_id=f_rb if inst == Institution.RAIFFEISEN else f_rev,
            original_file_hash=h_rb if inst == Institution.RAIFFEISEN else h_rev,
        )

    # --- Shopping / health / cash ---
    extras = [
        (3, 28, "-2490", "Demo Electronics", CAT_ELECTRONICS, ACC_REV_CZK, Institution.REVOLUT),
        (4, 15, "-1290", "Demo Apparel", CAT_CLOTHING, ACC_RB, Institution.RAIFFEISEN),
        (5, 12, "-890", "Demo Pharmacy", CAT_PHARMACY, ACC_REV_CZK, Institution.REVOLUT),
        (6, 3, "-3200", "Demo Store", CAT_SHOP_GENERAL, ACC_RB, Institution.RAIFFEISEN),
        (7, 15, "-4500", "ATM Raiffeisen", CAT_CASH_WITHDRAWAL, ACC_RB, Institution.RAIFFEISEN),
        (8, 4, "-1590", "Demo Apparel", CAT_CLOTHING, ACC_REV_CZK, Institution.REVOLUT),
        (4, 28, "-80", "Bank fee", CAT_BANK_FEES, ACC_RB, Institution.RAIFFEISEN),
        (7, 1, "-80", "Bank fee", CAT_BANK_FEES, ACC_RB, Institution.RAIFFEISEN),
        (5, 30, "2500", "Freelance Demo Client", CAT_OTHER_INCOME, ACC_REV_CZK, Institution.REVOLUT),
    ]
    for mo, day, amt, merch, cat, acc, inst in extras:
        add(
            account_id=acc,
            day=date(2026, mo, day),
            amount=amt,
            currency="CZK",
            institution=inst,
            merchant=merch,
            description=merch,
            category_id=cat,
            source_file_id=f_rb if inst == Institution.RAIFFEISEN else f_rev,
            original_file_hash=h_rb if inst == Institution.RAIFFEISEN else h_rev,
        )

    # --- USD shopping ---
    add(
        account_id=ACC_REV_USD,
        day=date(2026, 5, 20),
        amount="-49.99",
        currency="USD",
        institution=Institution.REVOLUT,
        merchant="Demo Cloud Shop",
        description="Online purchase",
        category_id=CAT_SHOP_GENERAL,
        source_file_id=f_rev,
        original_file_hash=h_rev,
    )
    add(
        account_id=ACC_REV_USD,
        day=date(2026, 7, 8),
        amount="-29.00",
        currency="USD",
        institution=Institution.REVOLUT,
        merchant="Demo Books",
        description="Online purchase",
        category_id=CAT_SHOP_GENERAL,
        source_file_id=f_rev,
        original_file_hash=h_rev,
    )

    # --- Internal transfer pair (wallet ↔ bank) — must not hit income/expense ---
    add(
        account_id=ACC_REV_CZK,
        day=date(2026, 7, 20),
        amount="-10000",
        currency="CZK",
        institution=Institution.REVOLUT,
        description="Transfer to own bank",
        original_description="Transfer to own bank account",
        category_id=CAT_INTERNAL,
        is_internal=True,
        transfer_group_id=XFER_GROUP_REV_RB,
        source_file_id=f_rev,
        original_file_hash=h_rev,
    )
    add(
        account_id=ACC_RB,
        day=date(2026, 7, 20),
        amount="10000",
        currency="CZK",
        institution=Institution.RAIFFEISEN,
        description="Incoming payment from wallet",
        original_description="Sent from Revolut",
        category_id=CAT_INTERNAL,
        is_internal=True,
        transfer_group_id=XFER_GROUP_REV_RB,
        counterparty_name="Revolut",
        source_file_id=f_rb,
        original_file_hash=h_rb,
    )

    # --- Crypto pot funding (Digital Assets Europe) — internal + crypto funding ---
    da_group = UUID("aa300001-0000-4000-8000-000000000001")
    add(
        account_id=ACC_REV_CZK,
        day=date(2026, 6, 10),
        amount="-5000",
        currency="CZK",
        institution=Institution.REVOLUT,
        description="Revolut Digital Assets Europe Ltd",
        original_description="Transfer to Revolut Digital Assets Europe Ltd",
        category_id=CAT_CRYPTO_FUND,
        is_internal=True,
        transfer_group_id=da_group,
        source_file_id=f_rev,
        original_file_hash=h_rev,
    )
    add(
        account_id=ACC_REV_CRYPTO,
        day=date(2026, 6, 10),
        amount="216.45",
        currency="USD",
        institution=Institution.REVOLUT,
        description="Crypto pot top-up",
        original_description="From Revolut Digital Assets Europe Ltd",
        category_id=CAT_CRYPTO_FUND,
        is_internal=True,
        transfer_group_id=da_group,
        source_file_id=f_rev,
        original_file_hash=h_rev,
    )

    # --- Broker funding ---
    add(
        account_id=ACC_REV_USD,
        day=date(2026, 4, 2),
        amount="-500.00",
        currency="USD",
        institution=Institution.REVOLUT,
        description="Transfer to eToro",
        category_id=CAT_BROKER,
        source_file_id=f_stk,
        original_file_hash=h_stk,
    )
    add(
        account_id=ACC_ETORO,
        day=date(2026, 4, 2),
        amount="500.00",
        currency="USD",
        institution=Institution.ETORO,
        description="eToro deposit",
        category_id=CAT_BROKER,
        is_internal=True,
        source_file_id=f_stk,
        original_file_hash=h_stk,
    )

    # External transfer (not internal)
    add(
        account_id=ACC_REV_CZK,
        day=date(2026, 5, 27),
        amount="-1500",
        currency="CZK",
        institution=Institution.REVOLUT,
        description="Transfer to friend",
        original_description="Transfer to Demo Friend",
        category_id=CAT_EXTERNAL_XFER,
        merchant="Demo Friend",
        source_file_id=f_rev,
        original_file_hash=h_rev,
    )

    return rows


DEMO_TOUR_TRANSACTIONS: list[Transaction] = _build_tour_transactions()

FILE_RB = _file_id(1)
FILE_REV = _file_id(2)
FILE_STK = _file_id(3)

DEMO_STATEMENT_FILES: list[StatementFile] = [
    StatementFile(
        id=FILE_RB,
        original_filename="raiffeisen_checking_2026.csv",
        uploaded_at=_TS,
        content_sha256=_hash(1),
        institution=Institution.RAIFFEISEN.value,
        row_count=80,
        parser_key=ParserKey.RAIFFEISEN_CZ.value,
        status=StatementFileStatus.IMPORTED,
        notes="demo synthetic import",
        created_at=_TS,
        updated_at=_TS,
    ),
    StatementFile(
        id=FILE_REV,
        original_filename="revolut_checking_expenses_2026.csv",
        uploaded_at=_TS,
        content_sha256=_hash(2),
        institution=Institution.REVOLUT.value,
        row_count=90,
        parser_key=ParserKey.REVOLUT_EXPENSES.value,
        status=StatementFileStatus.IMPORTED,
        notes="demo synthetic import",
        created_at=_TS,
        updated_at=_TS,
    ),
    StatementFile(
        id=FILE_STK,
        original_filename="etoro_activity_2026.csv",
        uploaded_at=_TS,
        content_sha256=_hash(3),
        institution=Institution.ETORO.value,
        row_count=12,
        parser_key=ParserKey.ETORO_ACTIVITY.value,
        status=StatementFileStatus.IMPORTED,
        notes="demo synthetic import",
        created_at=_TS,
        updated_at=_TS,
    ),
]


# Real Yahoo/yfinance-friendly tickers (crypto ETH → ETH-USD via PriceService).
LOT_AAPL = _lot_id(1)
LOT_MSFT = _lot_id(2)
LOT_ETH = _lot_id(3)
LOT_VTI = _lot_id(4)
EVT_BUY_AAPL = _evt_id(1)
EVT_BUY_MSFT = _evt_id(2)
EVT_BUY_ETH = _evt_id(3)
EVT_BUY_VTI = _evt_id(4)
EVT_SELL_MSFT = _evt_id(5)

_FAKE_TICKERS = frozenset({"DEMO", "SAMPLE"})

DEMO_TOUR_LOTS: list[InvestmentLot] = [
    InvestmentLot(
        id=LOT_AAPL,
        account_id=ACC_REV_STOCKS,
        ticker="AAPL",
        asset_class=AssetClass.STOCK,
        source=Institution.REVOLUT.value,
        acquisition_date=date(2024, 1, 15),
        quantity_opened=Decimal("10"),
        quantity_remaining=Decimal("10"),
        cost_basis_native=Decimal("1850.00"),
        cost_basis_czk=Decimal("42735.00"),
        cost_basis_usd=Decimal("1850.00"),
        native_currency="USD",
        open_event_id=EVT_BUY_AAPL,
        status=LotStatus.OPEN,
        notes="demo synthetic lot — live quotes via yfinance",
        created_at=_TS,
        updated_at=_TS,
    ),
    InvestmentLot(
        id=LOT_MSFT,
        account_id=ACC_ETORO,
        ticker="MSFT",
        asset_class=AssetClass.STOCK,
        source=Institution.ETORO.value,
        acquisition_date=date(2025, 3, 1),
        quantity_opened=Decimal("8"),
        quantity_remaining=Decimal("6"),
        cost_basis_native=Decimal("2520.00"),
        cost_basis_czk=Decimal("58212.00"),
        cost_basis_usd=Decimal("2520.00"),
        native_currency="USD",
        open_event_id=EVT_BUY_MSFT,
        status=LotStatus.OPEN,
        notes="demo synthetic — partial sell applied",
        created_at=_TS,
        updated_at=_TS,
    ),
    InvestmentLot(
        id=LOT_ETH,
        account_id=ACC_REV_CRYPTO,
        ticker="ETH",
        asset_class=AssetClass.CRYPTO,
        source=Institution.REVOLUT.value,
        acquisition_date=date(2025, 6, 10),
        quantity_opened=Decimal("0.50"),
        quantity_remaining=Decimal("0.50"),
        cost_basis_native=Decimal("1200.00"),
        cost_basis_czk=Decimal("27720.00"),
        cost_basis_usd=Decimal("1200.00"),
        native_currency="USD",
        open_event_id=EVT_BUY_ETH,
        status=LotStatus.OPEN,
        notes="demo synthetic crypto lot (Yahoo ETH-USD)",
        created_at=_TS,
        updated_at=_TS,
    ),
    InvestmentLot(
        id=LOT_VTI,
        account_id=ACC_ETORO,
        ticker="VTI",
        asset_class=AssetClass.ETF,
        source=Institution.ETORO.value,
        acquisition_date=date(2026, 4, 2),
        quantity_opened=Decimal("4"),
        quantity_remaining=Decimal("4"),
        cost_basis_native=Decimal("1000.00"),
        cost_basis_czk=Decimal("23100.00"),
        cost_basis_usd=Decimal("1000.00"),
        native_currency="USD",
        open_event_id=EVT_BUY_VTI,
        status=LotStatus.OPEN,
        notes="demo synthetic ETF lot",
        created_at=_TS,
        updated_at=_TS,
    ),
]

DEMO_TOUR_EVENTS: list[InvestmentEvent] = [
    InvestmentEvent(
        id=EVT_BUY_AAPL,
        account_id=ACC_REV_STOCKS,
        event_type=InvestmentEventType.BUY,
        event_date=date(2024, 1, 15),
        ticker="AAPL",
        asset_class=AssetClass.STOCK,
        side=TradeSide.BUY,
        quantity=Decimal("10"),
        price_native=Decimal("185.00"),
        native_currency="USD",
        value_native=Decimal("1850.00"),
        value_usd=Decimal("1850.00"),
        value_czk=Decimal("42735.00"),
        lot_id=LOT_AAPL,
        source=Institution.REVOLUT.value,
        external_id="demo-evt-0001",
        description="Buy AAPL",
        created_at=_TS,
        updated_at=_TS,
    ),
    InvestmentEvent(
        id=EVT_BUY_MSFT,
        account_id=ACC_ETORO,
        event_type=InvestmentEventType.BUY,
        event_date=date(2025, 3, 1),
        ticker="MSFT",
        asset_class=AssetClass.STOCK,
        side=TradeSide.BUY,
        quantity=Decimal("8"),
        price_native=Decimal("420.00"),
        native_currency="USD",
        value_native=Decimal("3360.00"),
        value_usd=Decimal("3360.00"),
        value_czk=Decimal("77616.00"),
        lot_id=LOT_MSFT,
        source=Institution.ETORO.value,
        external_id="demo-evt-0002",
        description="Buy MSFT",
        created_at=_TS,
        updated_at=_TS,
    ),
    InvestmentEvent(
        id=EVT_SELL_MSFT,
        account_id=ACC_ETORO,
        event_type=InvestmentEventType.SELL,
        event_date=date(2025, 11, 10),
        ticker="MSFT",
        asset_class=AssetClass.STOCK,
        side=TradeSide.SELL,
        quantity=Decimal("2"),
        price_native=Decimal("430.00"),
        native_currency="USD",
        value_native=Decimal("860.00"),
        value_usd=Decimal("860.00"),
        value_czk=Decimal("19866.00"),
        lot_id=LOT_MSFT,
        source=Institution.ETORO.value,
        external_id="demo-evt-0005",
        description="Partial sell MSFT",
        realized_gain_usd=Decimal("20.00"),
        realized_gain_czk=Decimal("462.00"),
        holding_period_days=254,
        qualifies_3y_exemption=False,
        created_at=_TS,
        updated_at=_TS,
    ),
    InvestmentEvent(
        id=EVT_BUY_ETH,
        account_id=ACC_REV_CRYPTO,
        event_type=InvestmentEventType.BUY,
        event_date=date(2025, 6, 10),
        ticker="ETH",
        asset_class=AssetClass.CRYPTO,
        side=TradeSide.BUY,
        quantity=Decimal("0.50"),
        price_native=Decimal("2400.00"),
        native_currency="USD",
        value_native=Decimal("1200.00"),
        value_usd=Decimal("1200.00"),
        value_czk=Decimal("27720.00"),
        lot_id=LOT_ETH,
        source=Institution.REVOLUT.value,
        external_id="demo-evt-0003",
        description="Buy ETH",
        created_at=_TS,
        updated_at=_TS,
    ),
    InvestmentEvent(
        id=EVT_BUY_VTI,
        account_id=ACC_ETORO,
        event_type=InvestmentEventType.BUY,
        event_date=date(2026, 4, 2),
        ticker="VTI",
        asset_class=AssetClass.ETF,
        side=TradeSide.BUY,
        quantity=Decimal("4"),
        price_native=Decimal("250.00"),
        native_currency="USD",
        value_native=Decimal("1000.00"),
        value_usd=Decimal("1000.00"),
        value_czk=Decimal("23100.00"),
        lot_id=LOT_VTI,
        source=Institution.ETORO.value,
        external_id="demo-evt-0004",
        description="Buy VTI",
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
    existing_acc = repo.list_rows("Accounts")
    acc_names = {str(getattr(a, "name", "") or "") for a in existing_acc}
    # Upgrade placeholder "Demo Bank/Wallet" names to real institution labels.
    need_accounts = (
        not existing_acc
        or any(n.startswith("Demo ") for n in acc_names)
        or "Raiffeisen CZK" not in acc_names
        or "Revolut CZK" not in acc_names
        or "eToro" not in acc_names
    )
    if need_accounts:
        repo.replace_all_rows("Accounts", list(DEMO_ACCOUNTS))
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

    # Upgrade sparse seeds (e.g. older 5-row tour) after deploys.
    existing_tx = repo.list_rows("Transactions")
    if len(existing_tx) < _TOUR_TX_MIN:
        repo.replace_all_rows("Transactions", list(DEMO_TOUR_TRANSACTIONS))
    if not repo.list_rows("StatementFiles"):
        try:
            repo.upsert_rows("StatementFiles", DEMO_STATEMENT_FILES)
        except Exception:  # noqa: BLE001
            pass
    existing_lots = repo.list_rows("InvestmentLots")
    lot_tickers = {
        str(getattr(r, "ticker", "") or "").upper()
        for r in existing_lots
    }
    need_lots = (
        DEMO_TOUR_LOTS
        and (
            len(existing_lots) < 3
            or bool(lot_tickers & _FAKE_TICKERS)
            or not {"AAPL", "MSFT", "ETH", "VTI"}.issubset(lot_tickers)
        )
    )
    if need_lots:
        try:
            repo.replace_all_rows("InvestmentLots", list(DEMO_TOUR_LOTS))
        except Exception:  # noqa: BLE001
            pass
    existing_evts = repo.list_rows("InvestmentEvents")
    evt_tickers = {
        str(getattr(r, "ticker", "") or "").upper()
        for r in existing_evts
    }
    need_evts = (
        DEMO_TOUR_EVENTS
        and (
            len(existing_evts) < 3
            or bool(evt_tickers & _FAKE_TICKERS)
            or not {"AAPL", "MSFT", "ETH", "VTI"}.issubset(evt_tickers)
        )
    )
    if need_evts:
        try:
            repo.replace_all_rows("InvestmentEvents", list(DEMO_TOUR_EVENTS))
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
