"""
Sample seed rows aligned with real CSV structures in Bank statements/.

UUIDs are fixed for documentation and cross-row FK stability in examples.
Includes **Digital Assets Europe** category rule (priority 6) so greenfield
imports treat crypto pot cash legs as internal + Crypto funding.

No personal counterparty keywords (Gauntlet strip-PII policy).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from backend.schema.default_categories import CAT_CRYPTO_FUND

from .models import (
    Account,
    AccountType,
    AssetClass,
    Category,
    CategoryRule,
    FXRate,
    FXSource,
    Institution,
    InvestmentEvent,
    InvestmentEventType,
    InvestmentLot,
    LifeDomain,
    LotStatus,
    MatchField,
    MatchType,
    Necessity,
    ParserKey,
    Setting,
    SettingValueType,
    StatementFile,
    StatementFileStatus,
    TradeSide,
    Transaction,
)

UTC = timezone.utc


def _dt(year: int, month: int, day: int, h: int = 0, m: int = 0, s: int = 0) -> datetime:
    return datetime(year, month, day, h, m, s, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Stable IDs
# ---------------------------------------------------------------------------

ACC_RB = UUID("a1000001-0000-4000-8000-000000000001")
ACC_REV_CZK = UUID("a1000001-0000-4000-8000-000000000002")
ACC_REV_USD = UUID("a1000001-0000-4000-8000-000000000003")
ACC_REV_STOCKS = UUID("a1000001-0000-4000-8000-000000000004")
ACC_REV_CRYPTO = UUID("a1000001-0000-4000-8000-000000000005")
ACC_ETORO = UUID("a1000001-0000-4000-8000-000000000006")

FILE_RB = UUID("f1000001-0000-4000-8000-000000000001")
FILE_REV_EXP = UUID("f1000001-0000-4000-8000-000000000002")
FILE_REV_STK = UUID("f1000001-0000-4000-8000-000000000003")
FILE_REV_CRY = UUID("f1000001-0000-4000-8000-000000000004")
FILE_ETORO = UUID("f1000001-0000-4000-8000-000000000005")

CAT_SUBS = UUID("c1000001-0000-4000-8000-000000000001")
CAT_SPOTIFY = UUID("c1000001-0000-4000-8000-000000000002")
CAT_TRANSFERS = UUID("c1000001-0000-4000-8000-000000000003")
CAT_INTERNAL = UUID("c1000001-0000-4000-8000-000000000004")
CAT_INSURANCE = UUID("c1000001-0000-4000-8000-000000000005")
CAT_INCOME = UUID("c1000001-0000-4000-8000-000000000006")

XFER_GROUP_REV_RB = UUID("d1000001-0000-4000-8000-000000000001")

LOT_PLTR = UUID("b1000001-0000-4000-8000-000000000001")
LOT_ETH = UUID("b1000001-0000-4000-8000-000000000002")
LOT_SPCX = UUID("b1000001-0000-4000-8000-000000000003")
LOT_ADA = UUID("b1000001-0000-4000-8000-000000000004")
LOT_VALE = UUID("b1000001-0000-4000-8000-000000000005")

EVT_BUY_PLTR = UUID("e1000001-0000-4000-8000-000000000001")
EVT_BUY_ETH = UUID("e1000001-0000-4000-8000-000000000002")
EVT_SELL_ETH = UUID("e1000001-0000-4000-8000-000000000003")
EVT_ALLOC_ETH = UUID("e1000001-0000-4000-8000-000000000004")
EVT_BUY_SPCX = UUID("e1000001-0000-4000-8000-000000000005")
EVT_FEE_SPCX = UUID("e1000001-0000-4000-8000-000000000006")
EVT_STAKE_ADA = UUID("e1000001-0000-4000-8000-000000000007")
EVT_DEP_ETORO = UUID("e1000001-0000-4000-8000-000000000008")
EVT_SELL_VALE = UUID("e1000001-0000-4000-8000-000000000009")
EVT_ALLOC_VALE = UUID("e1000001-0000-4000-8000-00000000000a")

# Placeholder SHA-256 (64 hex chars) — real imports compute from file bytes
HASH_RB = "a" * 64
HASH_REV_EXP = "b" * 64
HASH_REV_STK = "c" * 64
HASH_REV_CRY = "d" * 64
HASH_ETORO = "e" * 64

SEED_TS = _dt(2026, 8, 5, 12, 0, 0)


# ---------------------------------------------------------------------------
# Seed collections
# ---------------------------------------------------------------------------

SEED_ACCOUNTS: list[Account] = [
    Account(
        id=ACC_RB,
        name="Raiffeisen CZK",
        institution=Institution.RAIFFEISEN,
        account_type=AccountType.CHECKING,
        currency="CZK",
        account_number_mask="2489943002/5500",
        is_active=True,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    Account(
        id=ACC_REV_CZK,
        name="Revolut CZK",
        institution=Institution.REVOLUT,
        account_type=AccountType.CHECKING,
        currency="CZK",
        is_active=True,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    Account(
        id=ACC_REV_USD,
        name="Revolut USD",
        institution=Institution.REVOLUT,
        account_type=AccountType.CHECKING,
        currency="USD",
        is_active=True,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    Account(
        id=ACC_REV_STOCKS,
        name="Revolut Stocks",
        institution=Institution.REVOLUT,
        account_type=AccountType.INVESTMENT,
        currency="USD",
        is_active=True,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    Account(
        id=ACC_REV_CRYPTO,
        name="Revolut Crypto",
        institution=Institution.REVOLUT,
        account_type=AccountType.CRYPTO,
        currency="USD",
        is_active=True,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    Account(
        id=ACC_ETORO,
        name="eToro",
        institution=Institution.ETORO,
        account_type=AccountType.INVESTMENT,
        currency="USD",
        is_active=True,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
]

SEED_STATEMENT_FILES: list[StatementFile] = [
    StatementFile(
        id=FILE_RB,
        original_filename="RB statemtn beginning to now.csv",
        uploaded_at=_dt(2026, 8, 1, 10, 0, 0),
        content_sha256=HASH_RB,
        institution=Institution.RAIFFEISEN.value,
        row_count=500,
        parser_key=ParserKey.RAIFFEISEN_CZ.value,
        status=StatementFileStatus.IMPORTED,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    StatementFile(
        id=FILE_REV_EXP,
        original_filename="revolut daily expenses all.csv",
        uploaded_at=_dt(2026, 8, 1, 10, 5, 0),
        content_sha256=HASH_REV_EXP,
        institution=Institution.REVOLUT.value,
        row_count=800,
        parser_key=ParserKey.REVOLUT_EXPENSES.value,
        status=StatementFileStatus.IMPORTED,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    StatementFile(
        id=FILE_REV_STK,
        original_filename="Revolut stocks.csv",
        uploaded_at=_dt(2026, 8, 1, 10, 10, 0),
        content_sha256=HASH_REV_STK,
        institution=Institution.REVOLUT.value,
        row_count=120,
        parser_key=ParserKey.REVOLUT_STOCKS.value,
        status=StatementFileStatus.IMPORTED,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    StatementFile(
        id=FILE_REV_CRY,
        original_filename="Revolut crypto.csv",
        uploaded_at=_dt(2026, 8, 1, 10, 15, 0),
        content_sha256=HASH_REV_CRY,
        institution=Institution.REVOLUT.value,
        row_count=80,
        parser_key=ParserKey.REVOLUT_CRYPTO.value,
        status=StatementFileStatus.IMPORTED,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    StatementFile(
        id=FILE_ETORO,
        original_filename="etoro_activity_import.csv",
        uploaded_at=_dt(2026, 8, 1, 10, 20, 0),
        content_sha256=HASH_ETORO,
        institution=Institution.ETORO.value,
        row_count=40,
        parser_key=ParserKey.ETORO_ACTIVITY.value,
        status=StatementFileStatus.IMPORTED,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
]

SEED_CATEGORIES: list[Category] = [
    Category(
        id=CAT_SUBS,
        name="Subscriptions",
        parent_id=None,
        necessity=Necessity.DISCRETIONARY,
        life_domain=LifeDomain.SUBSCRIPTIONS,
        is_income=False,
        is_transfer=False,
        sort_order=10,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    Category(
        id=CAT_SPOTIFY,
        name="Spotify",
        parent_id=CAT_SUBS,
        necessity=Necessity.DISCRETIONARY,
        life_domain=LifeDomain.SUBSCRIPTIONS,
        is_income=False,
        is_transfer=False,
        sort_order=11,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    Category(
        id=CAT_TRANSFERS,
        name="Transfers",
        parent_id=None,
        necessity=Necessity.FIXED,
        life_domain=LifeDomain.TRANSFERS,
        is_income=False,
        is_transfer=True,
        sort_order=20,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    Category(
        id=CAT_INTERNAL,
        name="Internal transfer",
        parent_id=CAT_TRANSFERS,
        necessity=Necessity.FIXED,
        life_domain=LifeDomain.TRANSFERS,
        is_income=False,
        is_transfer=True,
        sort_order=21,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    Category(
        id=CAT_INSURANCE,
        name="Insurance",
        parent_id=None,
        necessity=Necessity.FIXED,
        life_domain=LifeDomain.HEALTH,
        is_income=False,
        is_transfer=False,
        sort_order=30,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    Category(
        id=CAT_INCOME,
        name="Salary / income",
        parent_id=None,
        necessity=Necessity.FIXED,
        life_domain=LifeDomain.INCOME,
        is_income=True,
        is_transfer=False,
        sort_order=1,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
]

# Stable ID for Digital Assets Europe rule (seeded in PR2, not deferred to repair)
RULE_DIGITAL_ASSETS = UUID("aa100001-0000-4000-8000-000000000006")

SEED_CATEGORY_RULES: list[CategoryRule] = [
    # Priority 6 — crypto pot cash legs (Current ↔ Digital Assets Europe)
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
        notes="seed:digital_assets_crypto_pot",
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    CategoryRule(
        id=UUID("aa100001-0000-4000-8000-000000000001"),
        priority=10,
        match_field=MatchField.MERCHANT,
        match_type=MatchType.CONTAINS,
        match_value="Spotify",
        category_id=CAT_SPOTIFY,
        set_internal_transfer=False,
        institution_scope=None,
        is_active=True,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    CategoryRule(
        id=UUID("aa100001-0000-4000-8000-000000000002"),
        priority=20,
        match_field=MatchField.ORIGINAL_DESCRIPTION,
        match_type=MatchType.CONTAINS,
        match_value="Sent from Revolut",
        category_id=CAT_INTERNAL,
        set_internal_transfer=True,
        institution_scope=Institution.RAIFFEISEN.value,
        is_active=True,
        notes="Revolut → Raiffeisen incoming",
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    CategoryRule(
        id=UUID("aa100001-0000-4000-8000-000000000003"),
        priority=30,
        match_field=MatchField.MERCHANT,
        match_type=MatchType.CONTAINS,
        match_value="Allianz",
        category_id=CAT_INSURANCE,
        set_internal_transfer=False,
        institution_scope=Institution.RAIFFEISEN.value,
        is_active=True,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    CategoryRule(
        id=UUID("aa100001-0000-4000-8000-000000000004"),
        priority=40,
        match_field=MatchField.DESCRIPTION,
        match_type=MatchType.STARTS_WITH,
        match_value="Transfer to",
        category_id=CAT_TRANSFERS,
        set_internal_transfer=False,
        institution_scope=Institution.REVOLUT.value,
        is_active=True,
        notes="May be external; override when own account detected",
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
]

# From RB: Spotify -185 CZK; Allianz -1887; Revolut inbound 10000
# From Revolut expenses: matching -10000 CZK transfer; Bad Jeffs -2500
SEED_TRANSACTIONS: list[Transaction] = [
    Transaction(
        id=UUID("21000001-0000-4000-8000-000000000001"),
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
        original_description="Spotify P4510D3D70; Stockholm; SWE",
        source_institution=Institution.RAIFFEISEN.value,
        external_id="9295911738",
        category_id=CAT_SPOTIFY,
        is_internal_transfer=False,
        original_file_hash=HASH_RB,
        source_file_id=FILE_RB,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    Transaction(
        id=UUID("21000001-0000-4000-8000-000000000002"),
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
        external_id="9257001941",
        counterparty_account="2700/2700",
        category_id=CAT_INSURANCE,
        is_internal_transfer=False,
        original_file_hash=HASH_RB,
        source_file_id=FILE_RB,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    Transaction(
        id=UUID("21000001-0000-4000-8000-000000000003"),
        account_id=ACC_RB,
        booking_date=date(2026, 7, 20),
        value_date=date(2026, 7, 20),
        amount=Decimal("10000"),
        currency="CZK",
        amount_czk=Decimal("10000"),
        amount_usd=Decimal("432.90"),
        fee_amount=Decimal("0"),
        fee_currency="CZK",
        merchant=None,
        description="Incoming payment from Revolut",
        original_description="/ROC/281475534714843///URI/Sent from Revolut",
        source_institution=Institution.RAIFFEISEN.value,
        external_id="9256965657",
        counterparty_account="2001141349/0800",
        counterparty_name="Ceska sporitelna vyp",
        category_id=CAT_INTERNAL,
        is_internal_transfer=True,
        transfer_group_id=XFER_GROUP_REV_RB,
        original_file_hash=HASH_RB,
        source_file_id=FILE_RB,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    Transaction(
        id=UUID("21000001-0000-4000-8000-000000000004"),
        account_id=ACC_REV_CZK,
        booking_date=date(2026, 7, 20),
        value_date=date(2026, 7, 20),
        amount=Decimal("-10000"),
        currency="CZK",
        amount_czk=Decimal("-10000"),
        amount_usd=Decimal("-432.90"),
        fee_amount=Decimal("0"),
        fee_currency="CZK",
        description="Transfer to own Raiffeisen",
        original_description="Transfer to own bank account",
        source_institution=Institution.REVOLUT.value,
        category_id=CAT_INTERNAL,
        is_internal_transfer=True,
        transfer_group_id=XFER_GROUP_REV_RB,
        original_file_hash=HASH_REV_EXP,
        source_file_id=FILE_REV_EXP,
        notes="Paired with Raiffeisen inbound 10000 CZK",
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    Transaction(
        id=UUID("21000001-0000-4000-8000-000000000005"),
        account_id=ACC_REV_CZK,
        booking_date=date(2020, 7, 9),
        value_date=date(2020, 7, 8),
        amount=Decimal("-2500"),
        currency="CZK",
        amount_czk=Decimal("-2500"),
        fee_amount=Decimal("0"),
        fee_currency="CZK",
        merchant="Bad Jeffs Barbecue",
        description="Card Payment Bad Jeffs Barbecue",
        original_description="Bad Jeffs Barbecue",
        source_institution=Institution.REVOLUT.value,
        is_internal_transfer=False,
        original_file_hash=HASH_REV_EXP,
        source_file_id=FILE_REV_EXP,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
]

# CNB-style illustrative rates (not official historical quotes for seed)
USD_CZK_2021_11_10 = Decimal("21.93")
USD_CZK_2021_11_22 = Decimal("22.40")
USD_CZK_2021_11_25 = Decimal("22.55")
USD_CZK_2026_07_20 = Decimal("23.10")

# PLTR buy 986.26 USD
PLTR_COST_USD = Decimal("986.26")
PLTR_COST_CZK = (PLTR_COST_USD * USD_CZK_2021_11_10).quantize(Decimal("0.01"))

# ETH buy 700 USD; sell 0.11655496 of 0.172396 → remaining 0.05584104
ETH_QTY_OPEN = Decimal("0.172396")
ETH_QTY_SOLD = Decimal("0.11655496")
ETH_QTY_REMAIN = ETH_QTY_OPEN - ETH_QTY_SOLD
ETH_COST_OPEN_USD = Decimal("700.00")
ETH_COST_OPEN_CZK = (ETH_COST_OPEN_USD * USD_CZK_2021_11_10).quantize(Decimal("0.01"))
ETH_ALLOC_FRAC = ETH_QTY_SOLD / ETH_QTY_OPEN
ETH_COST_ALLOC_USD = (ETH_COST_OPEN_USD * ETH_ALLOC_FRAC).quantize(Decimal("0.01"))
ETH_COST_ALLOC_CZK = (ETH_COST_OPEN_CZK * ETH_ALLOC_FRAC).quantize(Decimal("0.01"))
ETH_COST_REMAIN_USD = ETH_COST_OPEN_USD - ETH_COST_ALLOC_USD
ETH_COST_REMAIN_CZK = ETH_COST_OPEN_CZK - ETH_COST_ALLOC_CZK
ETH_PROCEEDS_USD = Decimal("500.00")
ETH_PROCEEDS_CZK = (ETH_PROCEEDS_USD * USD_CZK_2021_11_25).quantize(Decimal("0.01"))
ETH_GAIN_USD = ETH_PROCEEDS_USD - ETH_COST_ALLOC_USD
ETH_GAIN_CZK = ETH_PROCEEDS_CZK - ETH_COST_ALLOC_CZK

# SPCX 9 * basis including 1 USD commission capitalized into lot
SPCX_GROSS = Decimal("1088.60")
SPCX_FEE = Decimal("1.00")
SPCX_COST_USD = SPCX_GROSS + SPCX_FEE
SPCX_COST_CZK = (SPCX_COST_USD * USD_CZK_2026_07_20).quantize(Decimal("0.01"))

# ADA staking reward
ADA_QTY = Decimal("6.362224")
ADA_VALUE_USD = Decimal("1.18")
ADA_VALUE_CZK = (ADA_VALUE_USD * Decimal("23.05")).quantize(Decimal("0.01"))

# VALE full sell
VALE_QTY = Decimal("84")
VALE_COST_USD = Decimal("1020.00")  # illustrative open cost
VALE_COST_CZK = (VALE_COST_USD * USD_CZK_2021_11_10).quantize(Decimal("0.01"))
VALE_PROCEEDS_USD = Decimal("1020.66")
VALE_PROCEEDS_CZK = (VALE_PROCEEDS_USD * USD_CZK_2021_11_22).quantize(Decimal("0.01"))

SEED_INVESTMENT_LOTS: list[InvestmentLot] = [
    InvestmentLot(
        id=LOT_PLTR,
        account_id=ACC_REV_STOCKS,
        ticker="PLTR",
        asset_class=AssetClass.STOCK,
        source=Institution.REVOLUT.value,
        acquisition_date=date(2021, 11, 10),
        quantity_opened=Decimal("44"),
        quantity_remaining=Decimal("44"),
        cost_basis_native=PLTR_COST_USD,
        cost_basis_czk=PLTR_COST_CZK,
        cost_basis_usd=PLTR_COST_USD,
        native_currency="USD",
        open_event_id=EVT_BUY_PLTR,
        status=LotStatus.OPEN,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    InvestmentLot(
        id=LOT_ETH,
        account_id=ACC_REV_CRYPTO,
        ticker="ETH",
        asset_class=AssetClass.CRYPTO,
        source=Institution.REVOLUT.value,
        acquisition_date=date(2021, 11, 18),
        quantity_opened=ETH_QTY_OPEN,
        quantity_remaining=ETH_QTY_REMAIN,
        cost_basis_native=ETH_COST_REMAIN_USD,
        cost_basis_czk=ETH_COST_REMAIN_CZK,
        cost_basis_usd=ETH_COST_REMAIN_USD,
        native_currency="USD",
        open_event_id=EVT_BUY_ETH,
        status=LotStatus.OPEN,
        notes="Partial FIFO sell 2021-11-25",
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    InvestmentLot(
        id=LOT_SPCX,
        account_id=ACC_ETORO,
        ticker="SPCX",
        asset_class=AssetClass.STOCK,
        source=Institution.ETORO.value,
        acquisition_date=date(2026, 7, 20),
        quantity_opened=Decimal("9"),
        quantity_remaining=Decimal("9"),
        cost_basis_native=SPCX_COST_USD,
        cost_basis_czk=SPCX_COST_CZK,
        cost_basis_usd=SPCX_COST_USD,
        native_currency="USD",
        open_event_id=EVT_BUY_SPCX,
        status=LotStatus.OPEN,
        notes="Includes 1.00 USD open commission in basis",
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    InvestmentLot(
        id=LOT_ADA,
        account_id=ACC_ETORO,
        ticker="ADA",
        asset_class=AssetClass.CRYPTO,
        source=Institution.ETORO.value,
        acquisition_date=date(2026, 7, 6),
        quantity_opened=ADA_QTY,
        quantity_remaining=ADA_QTY,
        cost_basis_native=ADA_VALUE_USD,
        cost_basis_czk=ADA_VALUE_CZK,
        cost_basis_usd=ADA_VALUE_USD,
        native_currency="USD",
        open_event_id=EVT_STAKE_ADA,
        status=LotStatus.OPEN,
        notes="Staking reward lot; acquisition_date = reward date",
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    InvestmentLot(
        id=LOT_VALE,
        account_id=ACC_REV_STOCKS,
        ticker="VALE",
        asset_class=AssetClass.STOCK,
        source=Institution.REVOLUT.value,
        acquisition_date=date(2021, 11, 15),
        quantity_opened=VALE_QTY,
        quantity_remaining=Decimal("0"),
        cost_basis_native=Decimal("0"),
        cost_basis_czk=Decimal("0"),
        cost_basis_usd=Decimal("0"),
        native_currency="USD",
        open_event_id=None,
        status=LotStatus.CLOSED,
        notes="Fully sold 2021-11-22; remaining basis zeroed",
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
]

SEED_INVESTMENT_EVENTS: list[InvestmentEvent] = [
    InvestmentEvent(
        id=EVT_BUY_PLTR,
        account_id=ACC_REV_STOCKS,
        event_type=InvestmentEventType.BUY,
        event_date=date(2021, 11, 10),
        event_datetime=datetime(2021, 11, 10, 19, 38, 19, tzinfo=UTC),
        ticker="PLTR",
        asset_class=AssetClass.STOCK,
        side=TradeSide.BUY,
        quantity=Decimal("44"),
        price_native=Decimal("22.36"),
        native_currency="USD",
        value_native=PLTR_COST_USD,
        fees_native=Decimal("0"),
        value_czk=PLTR_COST_CZK,
        value_usd=PLTR_COST_USD,
        lot_id=LOT_PLTR,
        source=Institution.REVOLUT.value,
        description="BUY - MARKET PLTR",
        original_description="BUY - MARKET,44,USD 22.36,USD 986.26",
        source_file_id=FILE_REV_STK,
        original_file_hash=HASH_REV_STK,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    InvestmentEvent(
        id=EVT_BUY_ETH,
        account_id=ACC_REV_CRYPTO,
        event_type=InvestmentEventType.BUY,
        event_date=date(2021, 11, 18),
        event_datetime=datetime(2021, 11, 18, 21, 35, 24, tzinfo=UTC),
        ticker="ETH",
        asset_class=AssetClass.CRYPTO,
        side=TradeSide.BUY,
        quantity=ETH_QTY_OPEN,
        price_native=Decimal("4060.42"),
        native_currency="USD",
        value_native=ETH_COST_OPEN_USD,
        fees_native=Decimal("21.00"),
        value_czk=ETH_COST_OPEN_CZK,
        value_usd=ETH_COST_OPEN_USD,
        fees_usd=Decimal("21.00"),
        lot_id=LOT_ETH,
        source=Institution.REVOLUT.value,
        description="Buy ETH",
        original_description="ETH,Buy,0.172396,$4,060.42,$700.00,$21.00",
        source_file_id=FILE_REV_CRY,
        original_file_hash=HASH_REV_CRY,
        notes="Fees capitalized into lot cost in full import pipeline",
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    InvestmentEvent(
        id=EVT_SELL_ETH,
        account_id=ACC_REV_CRYPTO,
        event_type=InvestmentEventType.SELL,
        event_date=date(2021, 11, 25),
        event_datetime=datetime(2021, 11, 25, 1, 26, 29, tzinfo=UTC),
        ticker="ETH",
        asset_class=AssetClass.CRYPTO,
        side=TradeSide.SELL,
        quantity=ETH_QTY_SOLD,
        price_native=Decimal("4289.82"),
        native_currency="USD",
        value_native=ETH_PROCEEDS_USD,
        fees_native=Decimal("10.34"),
        value_czk=ETH_PROCEEDS_CZK,
        value_usd=ETH_PROCEEDS_USD,
        fees_usd=Decimal("10.34"),
        source=Institution.REVOLUT.value,
        description="Sell ETH",
        original_description="ETH,Sell,0.11655496,$4,289.82,$500.00,$10.34",
        source_file_id=FILE_REV_CRY,
        original_file_hash=HASH_REV_CRY,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    InvestmentEvent(
        id=EVT_ALLOC_ETH,
        account_id=ACC_REV_CRYPTO,
        event_type=InvestmentEventType.LOT_ALLOCATION,
        event_date=date(2021, 11, 25),
        event_datetime=datetime(2021, 11, 25, 1, 26, 29, tzinfo=UTC),
        ticker="ETH",
        asset_class=AssetClass.CRYPTO,
        side=TradeSide.SELL,
        quantity=ETH_QTY_SOLD,
        native_currency="USD",
        value_native=ETH_PROCEEDS_USD,
        fees_native=Decimal("10.34"),
        value_czk=ETH_PROCEEDS_CZK,
        value_usd=ETH_PROCEEDS_USD,
        lot_id=LOT_ETH,
        parent_event_id=EVT_SELL_ETH,
        realized_gain_czk=ETH_GAIN_CZK,
        realized_gain_usd=ETH_GAIN_USD,
        holding_period_days=7,
        qualifies_3y_exemption=False,
        source=Institution.REVOLUT.value,
        description="FIFO allocation against ETH lot 2021-11-18",
        source_file_id=FILE_REV_CRY,
        original_file_hash=HASH_REV_CRY,
        notes=f"cost_allocated_usd={ETH_COST_ALLOC_USD}",
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    InvestmentEvent(
        id=EVT_BUY_SPCX,
        account_id=ACC_ETORO,
        event_type=InvestmentEventType.BUY,
        event_date=date(2026, 7, 20),
        ticker="SPCX",
        asset_class=AssetClass.STOCK,
        side=TradeSide.BUY,
        quantity=Decimal("9"),
        price_native=Decimal("120.9556"),
        native_currency="USD",
        value_native=SPCX_GROSS,
        fees_native=Decimal("0"),
        value_czk=(SPCX_GROSS * USD_CZK_2026_07_20).quantize(Decimal("0.01")),
        value_usd=SPCX_GROSS,
        lot_id=LOT_SPCX,
        source=Institution.ETORO.value,
        description="Open Position SPCX/USD 9 units",
        original_description="Buy,SPCX,Stocks,Buy,9,120.9556,USD,1088.60,0.00",
        source_file_id=FILE_ETORO,
        original_file_hash=HASH_ETORO,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    InvestmentEvent(
        id=EVT_FEE_SPCX,
        account_id=ACC_ETORO,
        event_type=InvestmentEventType.FEE,
        event_date=date(2026, 7, 20),
        ticker="SPCX",
        asset_class=AssetClass.STOCK,
        quantity=Decimal("0"),
        native_currency="USD",
        value_native=Decimal("-1.00"),
        fees_native=Decimal("0"),
        value_usd=Decimal("-1.00"),
        value_czk=(Decimal("-1.00") * USD_CZK_2026_07_20).quantize(Decimal("0.01")),
        parent_event_id=EVT_BUY_SPCX,
        source=Institution.ETORO.value,
        external_id="3519253305",
        description="Commission On Open for position 3519253305",
        original_description="Commission,SPCX,Stocks,,0,0,USD,-1.00,0.00",
        source_file_id=FILE_ETORO,
        original_file_hash=HASH_ETORO,
        notes="Capitalized into SPCX lot basis in seed",
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    InvestmentEvent(
        id=EVT_STAKE_ADA,
        account_id=ACC_ETORO,
        event_type=InvestmentEventType.STAKING_REWARD,
        event_date=date(2026, 7, 6),
        ticker="ADA",
        asset_class=AssetClass.CRYPTO,
        side=TradeSide.BUY,
        quantity=ADA_QTY,
        price_native=Decimal("0.1855"),
        native_currency="USD",
        value_native=ADA_VALUE_USD,
        fees_native=Decimal("0"),
        value_czk=ADA_VALUE_CZK,
        value_usd=ADA_VALUE_USD,
        lot_id=LOT_ADA,
        source=Institution.ETORO.value,
        description="Staking reward ADA/USD",
        original_description="Staking reward,ADA,Crypto,Buy,6.362224,0.1855,USD,1.18,0.00",
        source_file_id=FILE_ETORO,
        original_file_hash=HASH_ETORO,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    InvestmentEvent(
        id=EVT_DEP_ETORO,
        account_id=ACC_ETORO,
        event_type=InvestmentEventType.DEPOSIT,
        event_date=date(2026, 7, 20),
        ticker=None,
        asset_class=AssetClass.CASH,
        quantity=Decimal("0"),
        native_currency="USD",
        value_native=Decimal("1100.00"),
        fees_native=Decimal("0"),
        value_usd=Decimal("1100.00"),
        value_czk=(Decimal("1100.00") * USD_CZK_2026_07_20).quantize(Decimal("0.01")),
        source=Institution.ETORO.value,
        description="Deposit 1100.00 USD CreditCard",
        original_description="Deposit,,Cash,,0,0,USD,1100.00,0.00",
        source_file_id=FILE_ETORO,
        original_file_hash=HASH_ETORO,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    InvestmentEvent(
        id=EVT_SELL_VALE,
        account_id=ACC_REV_STOCKS,
        event_type=InvestmentEventType.SELL,
        event_date=date(2021, 11, 22),
        event_datetime=datetime(2021, 11, 22, 15, 8, 4, tzinfo=UTC),
        ticker="VALE",
        asset_class=AssetClass.STOCK,
        side=TradeSide.SELL,
        quantity=VALE_QTY,
        price_native=Decimal("12.15"),
        native_currency="USD",
        value_native=VALE_PROCEEDS_USD,
        fees_native=Decimal("0"),
        value_czk=VALE_PROCEEDS_CZK,
        value_usd=VALE_PROCEEDS_USD,
        source=Institution.REVOLUT.value,
        description="SELL - MARKET VALE",
        original_description="SELL - MARKET,84,USD 12.15,USD 1020.66",
        source_file_id=FILE_REV_STK,
        original_file_hash=HASH_REV_STK,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    InvestmentEvent(
        id=EVT_ALLOC_VALE,
        account_id=ACC_REV_STOCKS,
        event_type=InvestmentEventType.LOT_ALLOCATION,
        event_date=date(2021, 11, 22),
        event_datetime=datetime(2021, 11, 22, 15, 8, 4, tzinfo=UTC),
        ticker="VALE",
        asset_class=AssetClass.STOCK,
        side=TradeSide.SELL,
        quantity=VALE_QTY,
        native_currency="USD",
        value_native=VALE_PROCEEDS_USD,
        value_czk=VALE_PROCEEDS_CZK,
        value_usd=VALE_PROCEEDS_USD,
        lot_id=LOT_VALE,
        parent_event_id=EVT_SELL_VALE,
        realized_gain_czk=VALE_PROCEEDS_CZK - VALE_COST_CZK,
        realized_gain_usd=VALE_PROCEEDS_USD - VALE_COST_USD,
        holding_period_days=7,
        qualifies_3y_exemption=False,
        source=Institution.REVOLUT.value,
        description="FIFO allocation closes VALE lot",
        source_file_id=FILE_REV_STK,
        original_file_hash=HASH_REV_STK,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
]

SEED_FX_RATES: list[FXRate] = [
    FXRate(
        id=UUID("41000001-0000-4000-8000-000000000001"),
        rate_date=date(2021, 11, 10),
        base_currency="USD",
        quote_currency="CZK",
        rate=USD_CZK_2021_11_10,
        source=FXSource.CNB,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    FXRate(
        id=UUID("41000001-0000-4000-8000-000000000002"),
        rate_date=date(2021, 11, 25),
        base_currency="USD",
        quote_currency="CZK",
        rate=USD_CZK_2021_11_25,
        source=FXSource.CNB,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    FXRate(
        id=UUID("41000001-0000-4000-8000-000000000003"),
        rate_date=date(2026, 7, 20),
        base_currency="USD",
        quote_currency="CZK",
        rate=USD_CZK_2026_07_20,
        source=FXSource.CNB,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    FXRate(
        id=UUID("41000001-0000-4000-8000-000000000004"),
        rate_date=date(2026, 7, 28),
        base_currency="EUR",
        quote_currency="CZK",
        rate=Decimal("25.00"),
        source=FXSource.CNB,
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    FXRate(
        id=UUID("41000001-0000-4000-8000-000000000005"),
        rate_date=date(2021, 11, 10),
        base_currency="USD",
        quote_currency="CZK",
        rate=Decimal("21.93"),
        source=FXSource.REVOLUT_STATEMENT,
        notes="From Revolut stocks FX Rate column (illustrative)",
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
]

SEED_SETTINGS: list[Setting] = [
    Setting(
        id=UUID("51000001-0000-4000-8000-000000000001"),
        key="primary_display_currency",
        value="USD",
        value_type=SettingValueType.STRING,
        description="Primary UI / report display currency",
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    Setting(
        id=UUID("51000001-0000-4000-8000-000000000002"),
        key="secondary_display_currency",
        value="CZK",
        value_type=SettingValueType.STRING,
        description="Secondary display currency (tax-local)",
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    Setting(
        id=UUID("51000001-0000-4000-8000-000000000003"),
        key="tax_residency",
        value="CZ",
        value_type=SettingValueType.STRING,
        description="Tax residency country code",
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    Setting(
        id=UUID("51000001-0000-4000-8000-000000000004"),
        key="fx_preferred_source",
        value="CNB",
        value_type=SettingValueType.STRING,
        description="Preferred FX source for CZK conversion",
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    Setting(
        id=UUID("51000001-0000-4000-8000-000000000005"),
        key="holding_period_exemption_days",
        value="1095",
        value_type=SettingValueType.NUMBER,
        description="Days for Czech 3-year securities exemption (3*365)",
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    Setting(
        id=UUID("51000001-0000-4000-8000-000000000006"),
        key="fifo_lot_method",
        value="FIFO",
        value_type=SettingValueType.STRING,
        description="Default lot relief method",
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
    Setting(
        id=UUID("51000001-0000-4000-8000-000000000007"),
        key="timezone",
        value="Europe/Prague",
        value_type=SettingValueType.STRING,
        description="Local timezone for date boundaries",
        created_at=SEED_TS,
        updated_at=SEED_TS,
    ),
]


def all_seed_counts() -> dict[str, int]:
    return {
        "Accounts": len(SEED_ACCOUNTS),
        "StatementFiles": len(SEED_STATEMENT_FILES),
        "Categories": len(SEED_CATEGORIES),
        "CategoryRules": len(SEED_CATEGORY_RULES),
        "Transactions": len(SEED_TRANSACTIONS),
        "InvestmentLots": len(SEED_INVESTMENT_LOTS),
        "InvestmentEvents": len(SEED_INVESTMENT_EVENTS),
        "FXRates": len(SEED_FX_RATES),
        "Settings": len(SEED_SETTINGS),
    }
