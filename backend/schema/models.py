"""
Google Sheets data model for Gauntlet Finance App.

Pydantic v2 models mirror spreadsheet tabs exactly (Collective parity).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Institution(str, Enum):
    RAIFFEISEN = "Raiffeisen"
    REVOLUT = "Revolut"
    ETORO = "eToro"
    OTHER = "Other"


class AccountType(str, Enum):
    CHECKING = "Checking"
    SAVINGS = "Savings"
    INVESTMENT = "Investment"
    CRYPTO = "Crypto"
    CASH = "Cash"
    LOAN = "Loan"
    OTHER = "Other"


class AssetClass(str, Enum):
    STOCK = "Stock"
    CRYPTO = "Crypto"
    ETF = "ETF"
    CASH = "Cash"
    OTHER = "Other"


class LotStatus(str, Enum):
    OPEN = "Open"
    CLOSED = "Closed"
    TRANSFERRED_OUT = "TransferredOut"


class InvestmentEventType(str, Enum):
    BUY = "Buy"
    SELL = "Sell"
    STAKE = "Stake"
    STAKING_REWARD = "StakingReward"
    SPLIT = "Split"
    TRANSFER = "Transfer"
    FEE = "Fee"
    DEPOSIT = "Deposit"
    WITHDRAWAL = "Withdrawal"
    LOT_ALLOCATION = "LotAllocation"


class TradeSide(str, Enum):
    BUY = "Buy"
    SELL = "Sell"


class Necessity(str, Enum):
    FIXED = "Fixed"
    VARIABLE_NECESSITY = "VariableNecessity"
    DISCRETIONARY = "Discretionary"


class LifeDomain(str, Enum):
    HOUSING = "Housing"
    DEBT = "Debt"
    TRANSPORT = "Transport"
    FOOD = "Food"
    SUBSCRIPTIONS = "Subscriptions"
    HEALTH = "Health"
    INCOME = "Income"
    TRANSFERS = "Transfers"
    INVESTMENTS = "Investments"
    HOBBIES = "Hobbies"
    BUSINESS = "Business"
    CASH = "Cash"
    SHOPPING = "Shopping"
    ENTERTAINMENT = "Entertainment"
    FEES = "Fees"
    OTHER = "Other"


class MatchField(str, Enum):
    MERCHANT = "merchant"
    DESCRIPTION = "description"
    ORIGINAL_DESCRIPTION = "original_description"
    COUNTERPARTY_NAME = "counterparty_name"
    SOURCE_INSTITUTION = "source_institution"


class MatchType(str, Enum):
    EXACT = "exact"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    REGEX = "regex"


class FXSource(str, Enum):
    CNB = "CNB"
    ECB = "ECB"
    REVOLUT_STATEMENT = "RevolutStatement"
    MANUAL = "Manual"
    OTHER = "Other"


class StatementFileStatus(str, Enum):
    PENDING = "Pending"
    IMPORTED = "Imported"
    SKIPPED_DUPLICATE = "SkippedDuplicate"
    ERROR = "Error"


class SettingValueType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    JSON = "json"


class ParserKey(str, Enum):
    """Hints for the future parser phase; stored as string on StatementFiles."""

    RAIFFEISEN_CZ = "raiffeisen_cz"
    REVOLUT_EXPENSES = "revolut_expenses"
    REVOLUT_STOCKS = "revolut_stocks"
    REVOLUT_CRYPTO = "revolut_crypto"
    ETORO_ACTIVITY = "etoro_activity"
    # Official multi-sheet Excel account statement (primary eToro format)
    ETORO_ACCOUNT_STATEMENT = "etoro_account_statement"


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------


class SheetRow(BaseModel):
    """Every sheet row has a stable UUID PK and soft-delete/audit fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID
    archived: bool = False
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Tab models (column order matches intended sheet header order)
# ---------------------------------------------------------------------------


class Account(SheetRow):
    """Tab: Accounts"""

    name: str
    institution: Institution
    account_type: AccountType
    currency: str = Field(..., min_length=3, max_length=3, description="ISO 4217")
    account_number_mask: Optional[str] = None
    is_active: bool = True
    notes: Optional[str] = None


class Transaction(SheetRow):
    """Tab: Transactions — multi-currency cash ledger."""

    account_id: UUID
    booking_date: date
    value_date: Optional[date] = None
    amount: Decimal
    currency: str = Field(..., min_length=3, max_length=3)
    amount_czk: Optional[Decimal] = None
    amount_usd: Optional[Decimal] = None
    fee_amount: Decimal = Decimal("0")
    fee_currency: Optional[str] = None
    merchant: Optional[str] = None
    description: Optional[str] = None
    original_description: Optional[str] = None
    source_institution: str
    external_id: Optional[str] = None
    counterparty_account: Optional[str] = None
    counterparty_name: Optional[str] = None
    category_id: Optional[UUID] = None
    category_override: bool = False
    is_internal_transfer: bool = False
    transfer_group_id: Optional[UUID] = None
    original_file_hash: Optional[str] = None
    source_file_id: Optional[UUID] = None
    notes: Optional[str] = None


class InvestmentLot(SheetRow):
    """Tab: InvestmentLots — tax inventory with remaining qty/basis."""

    account_id: UUID
    ticker: str
    asset_class: AssetClass
    source: str
    acquisition_date: date
    quantity_opened: Decimal
    quantity_remaining: Decimal
    cost_basis_native: Decimal = Field(
        ..., description="Remaining total cost in native_currency"
    )
    cost_basis_czk: Decimal = Field(..., description="Remaining total cost in CZK")
    cost_basis_usd: Decimal = Field(..., description="Remaining total cost in USD")
    native_currency: str = Field(..., min_length=3, max_length=3)
    open_event_id: Optional[UUID] = None
    status: LotStatus = LotStatus.OPEN
    notes: Optional[str] = None


class InvestmentEvent(SheetRow):
    """Tab: InvestmentEvents — trades + LotAllocation children for FIFO."""

    account_id: UUID
    event_type: InvestmentEventType
    event_date: date
    event_datetime: Optional[datetime] = None
    ticker: Optional[str] = None
    asset_class: Optional[AssetClass] = None
    side: Optional[TradeSide] = None
    quantity: Optional[Decimal] = None
    price_native: Optional[Decimal] = None
    native_currency: Optional[str] = None
    value_native: Optional[Decimal] = None
    fees_native: Decimal = Decimal("0")
    value_czk: Optional[Decimal] = None
    value_usd: Optional[Decimal] = None
    fees_czk: Optional[Decimal] = None
    fees_usd: Optional[Decimal] = None
    lot_id: Optional[UUID] = None
    parent_event_id: Optional[UUID] = None
    transfer_group_id: Optional[UUID] = None
    realized_gain_czk: Optional[Decimal] = None
    realized_gain_usd: Optional[Decimal] = None
    holding_period_days: Optional[int] = None
    qualifies_3y_exemption: Optional[bool] = None
    source: str
    external_id: Optional[str] = None
    description: Optional[str] = None
    original_description: Optional[str] = None
    source_file_id: Optional[UUID] = None
    original_file_hash: Optional[str] = None
    notes: Optional[str] = None


class Category(SheetRow):
    """Tab: Categories — hierarchy + necessity + life_domain axes."""

    name: str
    parent_id: Optional[UUID] = None
    necessity: Necessity
    life_domain: LifeDomain
    is_income: bool = False
    is_transfer: bool = False
    sort_order: int = 0


class CategoryRule(SheetRow):
    """Tab: CategoryRules — auto-categorization (engine in later phase)."""

    priority: int
    match_field: MatchField
    match_type: MatchType
    match_value: str
    category_id: UUID
    set_internal_transfer: bool = False
    institution_scope: Optional[str] = None
    is_active: bool = True
    notes: Optional[str] = None


class FXRate(SheetRow):
    """Tab: FXRates — CNB preferred for tax conversion."""

    rate_date: date
    base_currency: str = Field(..., min_length=3, max_length=3)
    quote_currency: str = Field(..., min_length=3, max_length=3)
    rate: Decimal = Field(
        ...,
        description="Quote units per 1 base unit (CNB: CZK per 1 USD/EUR/…)",
        gt=0,
    )
    source: FXSource = FXSource.CNB
    notes: Optional[str] = None


class StatementFile(SheetRow):
    """Tab: StatementFiles — idempotent uploads via content SHA-256."""

    original_filename: str
    uploaded_at: datetime
    content_sha256: str = Field(..., min_length=64, max_length=64)
    institution: str
    row_count: int = Field(..., ge=0)
    parser_key: Optional[str] = None
    status: StatementFileStatus = StatementFileStatus.PENDING
    notes: Optional[str] = None


class Setting(SheetRow):
    """Tab: Settings — key/value user preferences."""

    key: str
    value: str
    value_type: SettingValueType = SettingValueType.STRING
    description: Optional[str] = None


class Price(SheetRow):
    """Tab: Prices — latest market quotes for open tickers (Yahoo/yfinance)."""

    ticker: str
    price: Decimal
    currency: str = Field(default="USD", min_length=3, max_length=3)
    as_of: datetime
    source: str = "yfinance"


class PortfolioSnapshot(SheetRow):
    """Tab: PortfolioSnapshots — daily MV / cost / tax-free markers for charts."""

    as_of: date
    total_market_value_usd: Optional[Decimal] = None
    total_cost_basis_usd: Optional[Decimal] = None
    unrealized_usd: Optional[Decimal] = None
    tax_free_now_usd: Optional[Decimal] = None
    source: str = "price_refresh"
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Sheet header order (for Google Sheets creation in a later phase)
# ---------------------------------------------------------------------------

SHEET_HEADERS: dict[str, list[str]] = {
    "Accounts": [
        "id",
        "name",
        "institution",
        "account_type",
        "currency",
        "account_number_mask",
        "is_active",
        "notes",
        "archived",
        "created_at",
        "updated_at",
    ],
    "Transactions": [
        "id",
        "account_id",
        "booking_date",
        "value_date",
        "amount",
        "currency",
        "amount_czk",
        "amount_usd",
        "fee_amount",
        "fee_currency",
        "merchant",
        "description",
        "original_description",
        "source_institution",
        "external_id",
        "counterparty_account",
        "counterparty_name",
        "category_id",
        "category_override",
        "is_internal_transfer",
        "transfer_group_id",
        "original_file_hash",
        "source_file_id",
        "notes",
        "archived",
        "created_at",
        "updated_at",
    ],
    "InvestmentLots": [
        "id",
        "account_id",
        "ticker",
        "asset_class",
        "source",
        "acquisition_date",
        "quantity_opened",
        "quantity_remaining",
        "cost_basis_native",
        "cost_basis_czk",
        "cost_basis_usd",
        "native_currency",
        "open_event_id",
        "status",
        "notes",
        "archived",
        "created_at",
        "updated_at",
    ],
    "InvestmentEvents": [
        "id",
        "account_id",
        "event_type",
        "event_date",
        "event_datetime",
        "ticker",
        "asset_class",
        "side",
        "quantity",
        "price_native",
        "native_currency",
        "value_native",
        "fees_native",
        "value_czk",
        "value_usd",
        "fees_czk",
        "fees_usd",
        "lot_id",
        "parent_event_id",
        "transfer_group_id",
        "realized_gain_czk",
        "realized_gain_usd",
        "holding_period_days",
        "qualifies_3y_exemption",
        "source",
        "external_id",
        "description",
        "original_description",
        "source_file_id",
        "original_file_hash",
        "notes",
        "archived",
        "created_at",
        "updated_at",
    ],
    "Categories": [
        "id",
        "name",
        "parent_id",
        "necessity",
        "life_domain",
        "is_income",
        "is_transfer",
        "sort_order",
        "archived",
        "created_at",
        "updated_at",
    ],
    "CategoryRules": [
        "id",
        "priority",
        "match_field",
        "match_type",
        "match_value",
        "category_id",
        "set_internal_transfer",
        "institution_scope",
        "is_active",
        "notes",
        "archived",
        "created_at",
        "updated_at",
    ],
    "FXRates": [
        "id",
        "rate_date",
        "base_currency",
        "quote_currency",
        "rate",
        "source",
        "notes",
        "archived",
        "created_at",
        "updated_at",
    ],
    "StatementFiles": [
        "id",
        "original_filename",
        "uploaded_at",
        "content_sha256",
        "institution",
        "row_count",
        "parser_key",
        "status",
        "notes",
        "archived",
        "created_at",
        "updated_at",
    ],
    "Settings": [
        "id",
        "key",
        "value",
        "value_type",
        "description",
        "archived",
        "created_at",
        "updated_at",
    ],
    "Prices": [
        "id",
        "ticker",
        "price",
        "currency",
        "as_of",
        "source",
        "archived",
        "created_at",
        "updated_at",
    ],
    "PortfolioSnapshots": [
        "id",
        "as_of",
        "total_market_value_usd",
        "total_cost_basis_usd",
        "unrealized_usd",
        "tax_free_now_usd",
        "source",
        "notes",
        "archived",
        "created_at",
        "updated_at",
    ],
}

TAB_MODEL: dict[str, type[SheetRow]] = {
    "Accounts": Account,
    "Transactions": Transaction,
    "InvestmentLots": InvestmentLot,
    "InvestmentEvents": InvestmentEvent,
    "Categories": Category,
    "CategoryRules": CategoryRule,
    "FXRates": FXRate,
    "StatementFiles": StatementFile,
    "Settings": Setting,
    "Prices": Price,
    "PortfolioSnapshots": PortfolioSnapshot,
}
