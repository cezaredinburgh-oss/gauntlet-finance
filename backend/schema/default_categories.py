"""
Default category tree for ensure-defaults + seed expansion.

Stable UUIDs so re-running ensure is idempotent across installs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from backend.schema.models import Category, LifeDomain, Necessity

UTC = timezone.utc
_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _id(n: int) -> UUID:
    return UUID(f"c2000001-0000-4000-8000-{n:012d}")


# ---------------------------------------------------------------------------
# Stable IDs (also referenced by bootstrap keyword rules)
# ---------------------------------------------------------------------------

CAT_INCOME = _id(1)
CAT_SALARY = _id(2)
CAT_OTHER_INCOME = _id(3)

CAT_HOUSING = _id(10)
CAT_RENT = _id(11)
CAT_UTILITIES = _id(12)
CAT_INTERNET = _id(13)

CAT_FOOD = _id(20)
CAT_GROCERIES = _id(21)
CAT_RESTAURANTS = _id(22)
CAT_COFFEE = _id(23)

CAT_TRANSPORT = _id(30)
CAT_FUEL_CAR = _id(31)
CAT_PUBLIC_TRANSIT = _id(32)
CAT_TAXI = _id(33)
CAT_CAR = _id(34)

CAT_HEALTH = _id(40)
CAT_INSURANCE = _id(41)
CAT_PHARMACY = _id(42)
CAT_MEDICAL = _id(43)
CAT_FITNESS = _id(44)

CAT_SUBSCRIPTIONS = _id(50)
CAT_STREAMING = _id(51)
CAT_SOFTWARE = _id(52)
CAT_OTHER_SUBS = _id(53)
CAT_SPOTIFY = _id(54)

CAT_SHOPPING = _id(60)
CAT_SHOP_GENERAL = _id(61)
CAT_ELECTRONICS = _id(62)
CAT_CLOTHING = _id(63)

CAT_ENTERTAINMENT = _id(70)
CAT_GOING_OUT = _id(71)

CAT_MOTORCYCLING = _id(80)
CAT_MOTO_FUEL = _id(81)
CAT_MOTO_GEAR = _id(82)
CAT_MOTO_SERVICE = _id(83)
CAT_MOTO_INSURANCE = _id(84)
CAT_MOTO_OTHER = _id(85)

CAT_CASH = _id(90)
CAT_CASH_WITHDRAWAL = _id(91)

CAT_DEBT = _id(100)
CAT_LOANS = _id(101)
CAT_CC_PAYMENT = _id(102)

CAT_TRANSFERS = _id(110)
CAT_INTERNAL = _id(111)
CAT_EXTERNAL_XFER = _id(112)

CAT_INVESTMENTS = _id(120)
CAT_BROKER = _id(121)
CAT_CRYPTO_FUND = _id(122)

CAT_FEES = _id(130)
CAT_BANK_FEES = _id(131)

CAT_OTHER = _id(140)
CAT_UNCATEGORIZED = _id(141)

# Business (3D-print / customer parts)
CAT_BUSINESS = _id(150)
CAT_BIZ_MATERIALS = _id(151)
CAT_BIZ_TOOLS = _id(152)
CAT_BIZ_SHIPPING = _id(153)
CAT_BIZ_OTHER = _id(154)
CAT_BIZ_INCOME = _id(155)

# Self-education (courses, training — not business materials)
CAT_SELF_EDUCATION = _id(160)


def _cat(
    id_: UUID,
    name: str,
    *,
    parent_id: UUID | None,
    necessity: Necessity,
    life_domain: LifeDomain,
    sort_order: int,
    is_income: bool = False,
    is_transfer: bool = False,
) -> Category:
    return Category(
        id=id_,
        name=name,
        parent_id=parent_id,
        necessity=necessity,
        life_domain=life_domain,
        is_income=is_income,
        is_transfer=is_transfer,
        sort_order=sort_order,
        created_at=_TS,
        updated_at=_TS,
    )


DEFAULT_CATEGORIES: list[Category] = [
    # Income
    _cat(CAT_INCOME, "Income", parent_id=None, necessity=Necessity.FIXED, life_domain=LifeDomain.INCOME, sort_order=1, is_income=True),
    _cat(CAT_SALARY, "Salary", parent_id=CAT_INCOME, necessity=Necessity.FIXED, life_domain=LifeDomain.INCOME, sort_order=2, is_income=True),
    _cat(CAT_OTHER_INCOME, "Other income", parent_id=CAT_INCOME, necessity=Necessity.FIXED, life_domain=LifeDomain.INCOME, sort_order=3, is_income=True),
    # Housing
    _cat(CAT_HOUSING, "Housing", parent_id=None, necessity=Necessity.FIXED, life_domain=LifeDomain.HOUSING, sort_order=10),
    _cat(CAT_RENT, "Rent", parent_id=CAT_HOUSING, necessity=Necessity.FIXED, life_domain=LifeDomain.HOUSING, sort_order=11),
    _cat(CAT_UTILITIES, "Utilities", parent_id=CAT_HOUSING, necessity=Necessity.FIXED, life_domain=LifeDomain.HOUSING, sort_order=12),
    _cat(CAT_INTERNET, "Internet / phone", parent_id=CAT_HOUSING, necessity=Necessity.FIXED, life_domain=LifeDomain.HOUSING, sort_order=13),
    # Food
    _cat(CAT_FOOD, "Food", parent_id=None, necessity=Necessity.VARIABLE_NECESSITY, life_domain=LifeDomain.FOOD, sort_order=20),
    _cat(CAT_GROCERIES, "Groceries", parent_id=CAT_FOOD, necessity=Necessity.VARIABLE_NECESSITY, life_domain=LifeDomain.FOOD, sort_order=21),
    _cat(CAT_RESTAURANTS, "Restaurants", parent_id=CAT_FOOD, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.FOOD, sort_order=22),
    _cat(CAT_COFFEE, "Coffee / cafes", parent_id=CAT_FOOD, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.FOOD, sort_order=23),
    # Transport
    _cat(CAT_TRANSPORT, "Transport", parent_id=None, necessity=Necessity.VARIABLE_NECESSITY, life_domain=LifeDomain.TRANSPORT, sort_order=30),
    _cat(CAT_FUEL_CAR, "Fuel (car)", parent_id=CAT_TRANSPORT, necessity=Necessity.VARIABLE_NECESSITY, life_domain=LifeDomain.TRANSPORT, sort_order=31),
    _cat(CAT_PUBLIC_TRANSIT, "Public transit", parent_id=CAT_TRANSPORT, necessity=Necessity.VARIABLE_NECESSITY, life_domain=LifeDomain.TRANSPORT, sort_order=32),
    _cat(CAT_TAXI, "Taxi / rideshare", parent_id=CAT_TRANSPORT, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.TRANSPORT, sort_order=33),
    _cat(CAT_CAR, "Car costs", parent_id=CAT_TRANSPORT, necessity=Necessity.VARIABLE_NECESSITY, life_domain=LifeDomain.TRANSPORT, sort_order=34),
    # Health
    _cat(CAT_HEALTH, "Health", parent_id=None, necessity=Necessity.VARIABLE_NECESSITY, life_domain=LifeDomain.HEALTH, sort_order=40),
    _cat(CAT_INSURANCE, "Insurance", parent_id=CAT_HEALTH, necessity=Necessity.FIXED, life_domain=LifeDomain.HEALTH, sort_order=41),
    _cat(CAT_PHARMACY, "Pharmacy", parent_id=CAT_HEALTH, necessity=Necessity.VARIABLE_NECESSITY, life_domain=LifeDomain.HEALTH, sort_order=42),
    _cat(CAT_MEDICAL, "Medical", parent_id=CAT_HEALTH, necessity=Necessity.VARIABLE_NECESSITY, life_domain=LifeDomain.HEALTH, sort_order=43),
    _cat(CAT_FITNESS, "Fitness", parent_id=CAT_HEALTH, necessity=Necessity.VARIABLE_NECESSITY, life_domain=LifeDomain.HEALTH, sort_order=44),
    # Subscriptions
    _cat(CAT_SUBSCRIPTIONS, "Subscriptions", parent_id=None, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.SUBSCRIPTIONS, sort_order=50),
    _cat(CAT_STREAMING, "Streaming", parent_id=CAT_SUBSCRIPTIONS, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.SUBSCRIPTIONS, sort_order=51),
    _cat(CAT_SOFTWARE, "Software", parent_id=CAT_SUBSCRIPTIONS, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.SUBSCRIPTIONS, sort_order=52),
    _cat(CAT_OTHER_SUBS, "Other subscriptions", parent_id=CAT_SUBSCRIPTIONS, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.SUBSCRIPTIONS, sort_order=53),
    _cat(CAT_SPOTIFY, "Spotify", parent_id=CAT_SUBSCRIPTIONS, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.SUBSCRIPTIONS, sort_order=54),
    # Shopping
    _cat(CAT_SHOPPING, "Shopping", parent_id=None, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.SHOPPING, sort_order=60),
    _cat(CAT_SHOP_GENERAL, "General shopping", parent_id=CAT_SHOPPING, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.SHOPPING, sort_order=61),
    _cat(CAT_ELECTRONICS, "Electronics", parent_id=CAT_SHOPPING, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.SHOPPING, sort_order=62),
    _cat(CAT_CLOTHING, "Clothing", parent_id=CAT_SHOPPING, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.SHOPPING, sort_order=63),
    # Entertainment
    _cat(CAT_ENTERTAINMENT, "Entertainment", parent_id=None, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.ENTERTAINMENT, sort_order=70),
    _cat(CAT_GOING_OUT, "Going out", parent_id=CAT_ENTERTAINMENT, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.ENTERTAINMENT, sort_order=71),
    # Motorcycling / Hobbies
    _cat(CAT_MOTORCYCLING, "Motorcycling", parent_id=None, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.HOBBIES, sort_order=80),
    _cat(CAT_MOTO_FUEL, "Moto fuel", parent_id=CAT_MOTORCYCLING, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.HOBBIES, sort_order=81),
    _cat(CAT_MOTO_GEAR, "Moto gear", parent_id=CAT_MOTORCYCLING, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.HOBBIES, sort_order=82),
    _cat(CAT_MOTO_SERVICE, "Moto service", parent_id=CAT_MOTORCYCLING, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.HOBBIES, sort_order=83),
    _cat(CAT_MOTO_INSURANCE, "Moto insurance", parent_id=CAT_MOTORCYCLING, necessity=Necessity.FIXED, life_domain=LifeDomain.HOBBIES, sort_order=84),
    _cat(CAT_MOTO_OTHER, "Moto other", parent_id=CAT_MOTORCYCLING, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.HOBBIES, sort_order=85),
    # Cash
    _cat(CAT_CASH, "Cash", parent_id=None, necessity=Necessity.VARIABLE_NECESSITY, life_domain=LifeDomain.CASH, sort_order=90),
    _cat(CAT_CASH_WITHDRAWAL, "Cash withdrawal", parent_id=CAT_CASH, necessity=Necessity.VARIABLE_NECESSITY, life_domain=LifeDomain.CASH, sort_order=91),
    # Debt
    _cat(CAT_DEBT, "Debt", parent_id=None, necessity=Necessity.FIXED, life_domain=LifeDomain.DEBT, sort_order=100),
    _cat(CAT_LOANS, "Loans", parent_id=CAT_DEBT, necessity=Necessity.FIXED, life_domain=LifeDomain.DEBT, sort_order=101),
    _cat(CAT_CC_PAYMENT, "Credit card payment", parent_id=CAT_DEBT, necessity=Necessity.FIXED, life_domain=LifeDomain.DEBT, sort_order=102),
    # Transfers
    _cat(CAT_TRANSFERS, "Transfers", parent_id=None, necessity=Necessity.FIXED, life_domain=LifeDomain.TRANSFERS, sort_order=110, is_transfer=True),
    _cat(CAT_INTERNAL, "Internal transfer", parent_id=CAT_TRANSFERS, necessity=Necessity.FIXED, life_domain=LifeDomain.TRANSFERS, sort_order=111, is_transfer=True),
    _cat(CAT_EXTERNAL_XFER, "External transfer", parent_id=CAT_TRANSFERS, necessity=Necessity.FIXED, life_domain=LifeDomain.TRANSFERS, sort_order=112, is_transfer=True),
    # Investments
    _cat(CAT_INVESTMENTS, "Investments", parent_id=None, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.INVESTMENTS, sort_order=120),
    _cat(CAT_BROKER, "Broker funding", parent_id=CAT_INVESTMENTS, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.INVESTMENTS, sort_order=121),
    _cat(CAT_CRYPTO_FUND, "Crypto funding", parent_id=CAT_INVESTMENTS, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.INVESTMENTS, sort_order=122),
    # Fees
    _cat(CAT_FEES, "Fees", parent_id=None, necessity=Necessity.VARIABLE_NECESSITY, life_domain=LifeDomain.FEES, sort_order=130),
    _cat(CAT_BANK_FEES, "Bank fees", parent_id=CAT_FEES, necessity=Necessity.VARIABLE_NECESSITY, life_domain=LifeDomain.FEES, sort_order=131),
    # Business (3D print / motorcycle parts for customers)
    _cat(CAT_BUSINESS, "My business", parent_id=None, necessity=Necessity.VARIABLE_NECESSITY, life_domain=LifeDomain.BUSINESS, sort_order=150),
    _cat(CAT_BIZ_MATERIALS, "Biz materials / filament", parent_id=CAT_BUSINESS, necessity=Necessity.VARIABLE_NECESSITY, life_domain=LifeDomain.BUSINESS, sort_order=151),
    _cat(CAT_BIZ_TOOLS, "Biz tools / equipment", parent_id=CAT_BUSINESS, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.BUSINESS, sort_order=152),
    _cat(CAT_BIZ_SHIPPING, "Biz shipping / logistics", parent_id=CAT_BUSINESS, necessity=Necessity.VARIABLE_NECESSITY, life_domain=LifeDomain.BUSINESS, sort_order=153),
    _cat(CAT_BIZ_OTHER, "Biz other expenses", parent_id=CAT_BUSINESS, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.BUSINESS, sort_order=154),
    _cat(CAT_BIZ_INCOME, "Business income", parent_id=CAT_INCOME, necessity=Necessity.FIXED, life_domain=LifeDomain.INCOME, sort_order=4, is_income=True),
    # Self-education (courses / training)
    _cat(
        CAT_SELF_EDUCATION,
        "Self-education",
        parent_id=None,
        necessity=Necessity.DISCRETIONARY,
        life_domain=LifeDomain.EDUCATION,
        sort_order=160,
    ),
    # Other
    _cat(CAT_OTHER, "Other", parent_id=None, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.OTHER, sort_order=900),
    _cat(CAT_UNCATEGORIZED, "Uncategorized", parent_id=CAT_OTHER, necessity=Necessity.DISCRETIONARY, life_domain=LifeDomain.OTHER, sort_order=901),
]

# name lower -> id for bootstrap mapping
DEFAULT_CATEGORY_BY_NAME: dict[str, UUID] = {c.name.lower(): c.id for c in DEFAULT_CATEGORIES}

# Re-export for callers that need lifestyle ids (public demos exclude these).
OWNER_LIFESTYLE_CATEGORY_IDS: frozenset[UUID] = frozenset(
    {
        CAT_MOTORCYCLING,
        CAT_MOTO_FUEL,
        CAT_MOTO_GEAR,
        CAT_MOTO_SERVICE,
        CAT_MOTO_INSURANCE,
        CAT_MOTO_OTHER,
        CAT_BUSINESS,
        CAT_BIZ_MATERIALS,
        CAT_BIZ_TOOLS,
        CAT_BIZ_SHIPPING,
        CAT_BIZ_OTHER,
        CAT_BIZ_INCOME,
    }
)
