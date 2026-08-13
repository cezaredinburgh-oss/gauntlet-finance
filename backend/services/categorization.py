"""Category tree ensure, bulk rule apply, and data-driven rule bootstrap."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from backend.common.timeutil import utc_now
from backend.engines.categorize import apply_category_rules, rule_matches
from backend.schema.default_categories import (
    CAT_BANK_FEES,
    CAT_BIZ_MATERIALS,
    CAT_BIZ_TOOLS,
    CAT_BROKER,
    CAT_CASH_WITHDRAWAL,
    CAT_CLOTHING,
    CAT_COFFEE,
    CAT_CRYPTO_FUND,
    CAT_ELECTRONICS,
    CAT_EXTERNAL_XFER,
    CAT_FITNESS,
    CAT_FUEL_CAR,
    CAT_GOING_OUT,
    CAT_GROCERIES,
    CAT_INSURANCE,
    CAT_INTERNAL,
    CAT_INTERNET,
    CAT_LOANS,
    CAT_MEDICAL,
    CAT_MOTORCYCLING,
    CAT_MOTO_FUEL,
    CAT_MOTO_GEAR,
    CAT_MOTO_INSURANCE,
    CAT_MOTO_OTHER,
    CAT_MOTO_SERVICE,
    CAT_PHARMACY,
    CAT_PUBLIC_TRANSIT,
    CAT_RENT,
    CAT_RESTAURANTS,
    CAT_SALARY,
    CAT_SELF_EDUCATION,
    CAT_SHOP_GENERAL,
    CAT_SOFTWARE,
    CAT_SPOTIFY,
    CAT_STREAMING,
    CAT_TAXI,
    CAT_UTILITIES,
    DEFAULT_CATEGORIES,
)
from backend.schema.models import (
    Category,
    CategoryRule,
    MatchField,
    MatchType,
    Transaction,
)
from backend.services.fx_amounts import build_fx_service, tx_signed_usd
from backend.services.response_cache import cache_invalidate
from backend.sheets.repository import SheetsRepository


def ensure_default_categories(repo: SheetsRepository) -> dict[str, Any]:
    """Upsert default category tree by stable id (idempotent)."""
    existing = {
        c.id: c
        for c in repo.list_rows("Categories")
        if isinstance(c, Category)
    }
    now = utc_now()
    to_write: list[Category] = []
    created = 0
    updated = 0
    for template in DEFAULT_CATEGORIES:
        cur = existing.get(template.id)
        if cur is None:
            to_write.append(template.model_copy(update={"created_at": now, "updated_at": now}))
            created += 1
        else:
            # Refresh name/axes if template is canonical; keep user notes via model
            refreshed = cur.model_copy(
                update={
                    "name": template.name,
                    "parent_id": template.parent_id,
                    "necessity": template.necessity,
                    "life_domain": template.life_domain,
                    "is_income": template.is_income,
                    "is_transfer": template.is_transfer,
                    "sort_order": template.sort_order,
                    "archived": False,
                    "updated_at": now,
                }
            )
            to_write.append(refreshed)
            updated += 1
    if to_write:
        repo.upsert_rows("Categories", to_write)
    # Seed Self-education exact-message rule (course payment) + Digital Assets pot rule
    from backend.schema.ensure_defaults import (
        ensure_digital_assets_rule,
        ensure_self_education_rule,
    )

    se_rule = ensure_self_education_rule(repo)
    da_rule = ensure_digital_assets_rule(repo)
    se_applied = apply_self_education_course_payments(repo)
    cache_invalidate()
    return {
        "created": created,
        "updated": updated,
        "total_defaults": len(DEFAULT_CATEGORIES),
        "self_education_rule": se_rule,
        "digital_assets_rule": da_rule,
        "self_education_category_id": str(CAT_SELF_EDUCATION),
        "self_education_txs_updated": se_applied.get("updated", 0),
    }


def apply_self_education_course_payments(repo: SheetsRepository) -> dict[str, Any]:
    """
    Assign Self-education only when message is ALL-CAPS ``CEZARY BIERNAT``.

    Title-case ``Cezary Biernat`` (common RB message noise) is not a course.
    Also clears false positives that were previously force-assigned.
    Skips category_override.
    """
    needle = "CEZARY BIERNAT"  # case-sensitive
    now = utc_now()
    dirty: list[Transaction] = []
    matched = 0
    cleared = 0
    skipped_override = 0
    already = 0
    for tx in repo.list_rows("Transactions"):
        if not isinstance(tx, Transaction) or tx.archived:
            continue
        orig = (tx.original_description or "").strip()
        desc = (tx.description or "").strip()
        hit = orig == needle or desc == f"Outgoing instant payment — {needle}"
        if hit:
            matched += 1
            if tx.category_override:
                skipped_override += 1
                continue
            if tx.category_id == CAT_SELF_EDUCATION:
                already += 1
                continue
            dirty.append(
                tx.model_copy(
                    update={
                        "category_id": CAT_SELF_EDUCATION,
                        "is_internal_transfer": False,
                        "updated_at": now,
                    }
                )
            )
            continue
        # Clear false positives: title-case / other messages wrongly set to Self-education
        if (
            tx.category_id == CAT_SELF_EDUCATION
            and not tx.category_override
            and orig != needle
        ):
            dirty.append(
                tx.model_copy(
                    update={
                        "category_id": None,
                        "updated_at": now,
                    }
                )
            )
            cleared += 1
    if dirty:
        repo.upsert_rows("Transactions", dirty)
        cache_invalidate()
    return {
        "matched": matched,
        "updated": matched - already - skipped_override if matched else 0,
        "assigned": len([1 for t in dirty if t.category_id == CAT_SELF_EDUCATION]),
        "cleared_false_positives": cleared,
        "already": already,
        "skipped_override": skipped_override,
    }


def apply_match_to_all_transactions(
    repo: SheetsRepository,
    *,
    category_id: UUID,
    match_field: str,
    match_type: str,
    match_value: str,
    institution_scope: str | None = None,
    set_internal_transfer: bool = False,
    mode: str = "reclassify_non_override",
    mark_override: bool = True,
) -> dict[str, Any]:
    """
    Apply a single match pattern to **all** transactions in the sheet
    (not limited to the current UI filter).

    Modes:
    - ``fill_blanks``: only empty category_id
    - ``reclassify_non_override``: any non-override row that matches (default)
    - ``force``: all matches including user overrides
    """
    from backend.schema.models import MatchField, MatchType

    cat = repo.get_by_id("Categories", category_id)
    if cat is None or not isinstance(cat, Category) or cat.archived:
        raise ValueError("Category not found")

    try:
        field = MatchField(match_field)
        mtype = MatchType(match_type)
    except ValueError as exc:
        raise ValueError(f"Invalid match field/type: {exc}") from exc

    needle = (match_value or "").strip()
    if not needle:
        raise ValueError("match_value is required")

    # Synthetic one-rule list reused by rule_matches
    probe = CategoryRule(
        id=uuid4(),
        priority=1,
        match_field=field,
        match_type=mtype,
        match_value=needle,
        category_id=category_id,
        set_internal_transfer=set_internal_transfer,
        institution_scope=institution_scope or None,
        is_active=True,
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    mode_n = (mode or "reclassify_non_override").strip().lower()
    if mode_n not in {"fill_blanks", "reclassify_non_override", "force"}:
        mode_n = "reclassify_non_override"

    now = utc_now()
    scanned = 0
    matched = 0
    updated_n = 0
    skipped_override = 0
    skipped_already = 0
    dirty: list[Transaction] = []

    for tx in repo.list_rows("Transactions"):
        if not isinstance(tx, Transaction) or tx.archived:
            continue
        scanned += 1
        if not rule_matches(tx, probe):
            continue
        matched += 1

        if mode_n != "force" and tx.category_override:
            skipped_override += 1
            continue
        if mode_n == "fill_blanks" and tx.category_id is not None:
            skipped_already += 1
            continue
        if (
            mode_n == "reclassify_non_override"
            and tx.category_id == category_id
            and (not set_internal_transfer or tx.is_internal_transfer)
        ):
            skipped_already += 1
            continue

        updates: dict[str, Any] = {
            "category_id": category_id,
            "updated_at": now,
        }
        if mark_override:
            updates["category_override"] = True
        if set_internal_transfer:
            updates["is_internal_transfer"] = True
        dirty.append(tx.model_copy(update=updates))
        updated_n += 1

    if dirty:
        repo.upsert_rows("Transactions", dirty)
        cache_invalidate()

    return {
        "scanned": scanned,
        "matched": matched,
        "updated": updated_n,
        "skipped_override": skipped_override,
        "skipped_already": skipped_already,
        "mode": mode_n,
        "category_id": str(category_id),
        "match_field": match_field,
        "match_type": match_type,
        "match_value": needle,
    }


def _is_blank_or_other_category(
    tx: Transaction,
    cats: dict[UUID, Category],
) -> bool:
    """True when rules may still improve this row (null / Other / Uncategorized)."""
    if tx.category_id is None:
        return True
    cat = cats.get(tx.category_id)
    if cat is None:
        return True
    name = (cat.name or "").strip().lower()
    if name in {"other", "uncategorized"}:
        return True
    if cat.life_domain is not None and cat.life_domain.value == "Other":
        return True
    return False


def apply_rules_fill_blanks(repo: SheetsRepository) -> dict[str, Any]:
    """
    Apply active rules to blank *and* residual Other/Uncategorized rows.

    Never touches category_override=True rows. Import often assigns Other as a
    fallback; treating only null as blank left coverage stuck after starter install.
    """
    rules = [
        r
        for r in repo.list_rows("CategoryRules")
        if isinstance(r, CategoryRule) and r.is_active and not r.archived
    ]
    cats = {
        c.id: c for c in repo.list_rows("Categories") if isinstance(c, Category)
    }
    txs = [t for t in repo.list_rows("Transactions") if isinstance(t, Transaction) and not t.archived]
    now = utc_now()
    dirty: list[Transaction] = []
    scanned = 0
    filled = 0
    skipped_override = 0
    skipped_already = 0
    unmatched = 0

    for tx in txs:
        scanned += 1
        if tx.category_override:
            skipped_override += 1
            continue
        if not _is_blank_or_other_category(tx, cats):
            skipped_already += 1
            continue
        updated = apply_category_rules(tx, rules, fallback_category_id=None)
        if (
            updated.category_id is not None
            and (
                updated.category_id != tx.category_id
                or updated.is_internal_transfer != tx.is_internal_transfer
            )
        ):
            dirty.append(updated.model_copy(update={"updated_at": now}))
            filled += 1
        else:
            unmatched += 1

    if dirty:
        # Batch upsert — still one tab flush, but only when there are changes
        repo.upsert_rows("Transactions", dirty)
    cache_invalidate()
    return {
        "scanned": scanned,
        "filled": filled,
        "skipped_override": skipped_override,
        "skipped_already": skipped_already,
        "unmatched": unmatched,
        "rules_used": len(rules),
    }


def apply_rules_reclassify_non_override(repo: SheetsRepository) -> dict[str, Any]:
    """
    Re-apply active rules to every non-override transaction.

    When a rule matches and the category (or internal flag) differs, update.
    Does not clear categories when no rule matches. Does not touch overrides.
    """
    rules = [
        r
        for r in repo.list_rows("CategoryRules")
        if isinstance(r, CategoryRule) and r.is_active and not r.archived
    ]
    txs = [t for t in repo.list_rows("Transactions") if isinstance(t, Transaction) and not t.archived]
    now = utc_now()
    dirty: list[Transaction] = []
    scanned = 0
    updated_n = 0
    skipped_override = 0
    unchanged = 0

    for tx in txs:
        scanned += 1
        if tx.category_override:
            skipped_override += 1
            continue
        updated = apply_category_rules(tx, rules, fallback_category_id=None)
        if (
            updated.category_id != tx.category_id
            or updated.is_internal_transfer != tx.is_internal_transfer
        ):
            dirty.append(updated.model_copy(update={"updated_at": now}))
            updated_n += 1
        else:
            unchanged += 1

    if dirty:
        repo.upsert_rows("Transactions", dirty)
    cache_invalidate()
    return {
        "scanned": scanned,
        "updated": updated_n,
        "unchanged": unchanged,
        "skipped_override": skipped_override,
        "rules_used": len(rules),
    }


def list_rules(repo: SheetsRepository) -> list[CategoryRule]:
    rows = [r for r in repo.list_rows("CategoryRules") if isinstance(r, CategoryRule) and not r.archived]
    rows.sort(key=lambda r: (r.priority, str(r.id)))
    return rows


def create_rule(repo: SheetsRepository, data: dict[str, Any]) -> CategoryRule:
    now = utc_now()
    rule = CategoryRule(
        id=uuid4(),
        priority=int(data.get("priority", 100)),
        match_field=MatchField(data["match_field"]),
        match_type=MatchType(data["match_type"]),
        match_value=str(data["match_value"]).strip(),
        category_id=UUID(str(data["category_id"])),
        set_internal_transfer=bool(data.get("set_internal_transfer", False)),
        institution_scope=data.get("institution_scope") or None,
        is_active=bool(data.get("is_active", True)),
        notes=data.get("notes"),
        created_at=now,
        updated_at=now,
    )
    repo.upsert_rows("CategoryRules", [rule])
    cache_invalidate()
    return rule


def update_rule(repo: SheetsRepository, rule_id: UUID, data: dict[str, Any]) -> CategoryRule | None:
    row = repo.get_by_id("CategoryRules", rule_id)
    if row is None or not isinstance(row, CategoryRule) or row.archived:
        return None
    updates: dict[str, Any] = {"updated_at": utc_now()}
    if "priority" in data and data["priority"] is not None:
        updates["priority"] = int(data["priority"])
    if "match_field" in data and data["match_field"]:
        updates["match_field"] = MatchField(data["match_field"])
    if "match_type" in data and data["match_type"]:
        updates["match_type"] = MatchType(data["match_type"])
    if "match_value" in data and data["match_value"] is not None:
        updates["match_value"] = str(data["match_value"]).strip()
    if "category_id" in data and data["category_id"]:
        updates["category_id"] = UUID(str(data["category_id"]))
    if "set_internal_transfer" in data:
        updates["set_internal_transfer"] = bool(data["set_internal_transfer"])
    if "institution_scope" in data:
        updates["institution_scope"] = data["institution_scope"] or None
    if "is_active" in data:
        updates["is_active"] = bool(data["is_active"])
    if "notes" in data:
        updates["notes"] = data["notes"]
    updated = row.model_copy(update=updates)
    repo.upsert_rows("CategoryRules", [updated])
    cache_invalidate()
    return updated


def deactivate_rule(repo: SheetsRepository, rule_id: UUID) -> bool:
    row = repo.get_by_id("CategoryRules", rule_id)
    if row is None or not isinstance(row, CategoryRule):
        return False
    updated = row.model_copy(update={"is_active": False, "updated_at": utc_now()})
    repo.upsert_rows("CategoryRules", [updated])
    cache_invalidate()
    return True


# (needle, match_field, category_id, priority, notes)
_KEYWORD_RULES: list[tuple[str, MatchField, UUID, int, str]] = [
    # Cash
    ("ATM", MatchField.DESCRIPTION, CAT_CASH_WITHDRAWAL, 5, "ATM cash"),
    ("Cash withdrawal", MatchField.DESCRIPTION, CAT_CASH_WITHDRAWAL, 5, "cash withdrawal"),
    ("Cash at", MatchField.DESCRIPTION, CAT_CASH_WITHDRAWAL, 5, "cash at"),
    ("Výběr", MatchField.DESCRIPTION, CAT_CASH_WITHDRAWAL, 5, "CZ ATM"),
    ("Vyber hotovosti", MatchField.DESCRIPTION, CAT_CASH_WITHDRAWAL, 5, "CZ cash"),
    # Motorcycling
    ("moto", MatchField.DESCRIPTION, CAT_MOTORCYCLING, 12, "moto keyword"),
    ("motocykl", MatchField.DESCRIPTION, CAT_MOTORCYCLING, 12, "motocykl"),
    ("motorcycle", MatchField.DESCRIPTION, CAT_MOTORCYCLING, 12, "motorcycle"),
    ("harley", MatchField.MERCHANT, CAT_MOTO_GEAR, 11, "harley"),
    ("ducati", MatchField.MERCHANT, CAT_MOTORCYCLING, 11, "ducati"),
    ("yamaha", MatchField.MERCHANT, CAT_MOTORCYCLING, 11, "yamaha"),
    ("kawasaki", MatchField.MERCHANT, CAT_MOTORCYCLING, 11, "kawasaki"),
    ("honda moto", MatchField.DESCRIPTION, CAT_MOTORCYCLING, 11, "honda moto"),
    ("motag", MatchField.MERCHANT, CAT_MOTO_GEAR, 11, "motag"),
    ("hein gericke", MatchField.MERCHANT, CAT_MOTO_GEAR, 11, "hein gericke"),
    ("polo motorrad", MatchField.MERCHANT, CAT_MOTO_GEAR, 11, "polo motorrad"),
    ("louis moto", MatchField.MERCHANT, CAT_MOTO_GEAR, 11, "louis"),
    ("motul", MatchField.MERCHANT, CAT_MOTO_SERVICE, 11, "motul oil"),
    ("ipone", MatchField.MERCHANT, CAT_MOTO_SERVICE, 11, "ipone"),
    ("pneu moto", MatchField.DESCRIPTION, CAT_MOTO_SERVICE, 11, "tires"),
    ("STK moto", MatchField.DESCRIPTION, CAT_MOTO_SERVICE, 11, "STK"),
    ("pov motocykl", MatchField.DESCRIPTION, CAT_MOTO_INSURANCE, 10, "CZ moto insurance"),
    ("motocyklov", MatchField.DESCRIPTION, CAT_MOTORCYCLING, 12, "motocyklov*"),
    ("4ride", MatchField.MERCHANT, CAT_MOTO_GEAR, 11, "4ride shop"),
    ("4RIDE", MatchField.MERCHANT, CAT_MOTO_GEAR, 11, "4ride shop"),
    ("revzilla", MatchField.MERCHANT, CAT_MOTO_GEAR, 11, "revzilla"),
    ("fc-moto", MatchField.MERCHANT, CAT_MOTO_GEAR, 11, "fc-moto"),
    ("chrome burnout", MatchField.MERCHANT, CAT_MOTO_GEAR, 11, "chrome burnout"),
    ("helmet", MatchField.DESCRIPTION, CAT_MOTO_GEAR, 14, "helmet"),
    ("helma", MatchField.DESCRIPTION, CAT_MOTO_GEAR, 14, "helma CZ"),
    ("motorrad", MatchField.DESCRIPTION, CAT_MOTORCYCLING, 12, "motorrad"),
    ("pneu", MatchField.DESCRIPTION, CAT_MOTO_SERVICE, 15, "pneu tires"),
    ("servis moto", MatchField.DESCRIPTION, CAT_MOTO_SERVICE, 11, "servis moto"),
    # Extra CZ retail / transit leftovers
    ("ZASILKOVNA", MatchField.MERCHANT, CAT_SHOP_GENERAL, 28, "zasilkovna"),
    ("ZÁSILKOVNA", MatchField.MERCHANT, CAT_SHOP_GENERAL, 28, "zasilkovna"),
    ("PACKETA", MatchField.MERCHANT, CAT_SHOP_GENERAL, 28, "packeta"),
    ("ALZA", MatchField.MERCHANT, CAT_SHOP_GENERAL, 24, "alza general shopping"),
    ("DATART", MatchField.MERCHANT, CAT_ELECTRONICS, 24, "datart"),
    ("CZC", MatchField.MERCHANT, CAT_ELECTRONICS, 24, "czc"),
    ("IKEA", MatchField.MERCHANT, CAT_SHOP_GENERAL, 26, "ikea"),
    ("HORNBACH", MatchField.MERCHANT, CAT_SHOP_GENERAL, 26, "hornbach"),
    ("OBI", MatchField.MERCHANT, CAT_SHOP_GENERAL, 26, "obi"),
    ("Decathlon", MatchField.MERCHANT, CAT_SHOP_GENERAL, 26, "decathlon"),
    ("mcdonald", MatchField.MERCHANT, CAT_RESTAURANTS, 28, "mcdonalds"),
    ("kfc", MatchField.MERCHANT, CAT_RESTAURANTS, 28, "kfc"),
    ("starbucks", MatchField.MERCHANT, CAT_COFFEE, 28, "starbucks"),
    ("bageterie", MatchField.MERCHANT, CAT_RESTAURANTS, 28, "bageterie"),
    # Groceries CZ/EU
    ("BILLA", MatchField.MERCHANT, CAT_GROCERIES, 20, "Billa"),
    ("LIDL", MatchField.MERCHANT, CAT_GROCERIES, 20, "Lidl"),
    ("ALBERT", MatchField.MERCHANT, CAT_GROCERIES, 20, "Albert"),
    ("TESCO", MatchField.MERCHANT, CAT_GROCERIES, 20, "Tesco"),
    ("KAUFLAND", MatchField.MERCHANT, CAT_GROCERIES, 20, "Kaufland"),
    ("PENNY", MatchField.MERCHANT, CAT_GROCERIES, 20, "Penny"),
    ("ROHLIK", MatchField.MERCHANT, CAT_GROCERIES, 20, "Rohlik"),
    ("ROHLÍK", MatchField.MERCHANT, CAT_GROCERIES, 20, "Rohlik diacritic"),
    ("KOSIK", MatchField.MERCHANT, CAT_GROCERIES, 20, "Kosik"),
    ("KOŠÍK", MatchField.MERCHANT, CAT_GROCERIES, 20, "Kosik"),
    ("GLOBUS", MatchField.MERCHANT, CAT_GROCERIES, 20, "Globus"),
    ("POTRAVINY", MatchField.MERCHANT, CAT_GROCERIES, 20, "potraviny"),
    ("DM DROGERIE", MatchField.MERCHANT, CAT_SHOP_GENERAL, 25, "DM"),
    ("ROSSMANN", MatchField.MERCHANT, CAT_SHOP_GENERAL, 25, "Rossmann"),
    # Bakery (not restaurants)
    ("ARTIC BAKEHOUSE", MatchField.MERCHANT, CAT_GROCERIES, 22, "artic bakehouse bakery"),
    ("BAKEHOUSE", MatchField.MERCHANT, CAT_GROCERIES, 24, "bakehouse bakery"),
    ("PEKARNA", MatchField.MERCHANT, CAT_GROCERIES, 24, "pekarna bakery"),
    ("PEKÁRNA", MatchField.MERCHANT, CAT_GROCERIES, 24, "pekarna bakery diacritic"),
    # Petrol → moto fuel (primary vehicle)
    ("SHELL", MatchField.MERCHANT, CAT_MOTO_FUEL, 22, "Shell moto fuel"),
    ("OMV", MatchField.MERCHANT, CAT_MOTO_FUEL, 22, "OMV moto fuel"),
    ("MOL ", MatchField.MERCHANT, CAT_MOTO_FUEL, 22, "MOL moto fuel"),
    ("MOL", MatchField.MERCHANT, CAT_MOTO_FUEL, 23, "MOL moto fuel exactish"),
    ("BENZINA", MatchField.MERCHANT, CAT_MOTO_FUEL, 22, "Benzina moto fuel"),
    ("ORLEN", MatchField.MERCHANT, CAT_MOTO_FUEL, 22, "Orlen moto fuel"),
    ("EUROOIL", MatchField.MERCHANT, CAT_MOTO_FUEL, 22, "EuroOil moto fuel"),
    ("TANK ONO", MatchField.MERCHANT, CAT_MOTO_FUEL, 22, "Tank ONO moto fuel"),
    ("BP ", MatchField.MERCHANT, CAT_MOTO_FUEL, 24, "BP moto fuel"),
    ("AMIC", MatchField.MERCHANT, CAT_MOTO_FUEL, 22, "AMIC Energy moto fuel"),
    ("HUNSGAS", MatchField.MERCHANT, CAT_MOTO_FUEL, 22, "Hunsgas moto fuel"),
    # Transit / rideshare
    ("PID", MatchField.MERCHANT, CAT_PUBLIC_TRANSIT, 22, "PID Prague"),
    ("DPP", MatchField.MERCHANT, CAT_PUBLIC_TRANSIT, 22, "DPP"),
    ("LÍTAČKA", MatchField.MERCHANT, CAT_PUBLIC_TRANSIT, 20, "litacka"),
    ("LITACKA", MatchField.MERCHANT, CAT_PUBLIC_TRANSIT, 20, "litacka ascii"),
    ("ČESKÉ DRÁHY", MatchField.MERCHANT, CAT_PUBLIC_TRANSIT, 20, "CD"),
    ("CESKE DRAHY", MatchField.MERCHANT, CAT_PUBLIC_TRANSIT, 20, "CD ascii"),
    ("UBER", MatchField.MERCHANT, CAT_TAXI, 22, "Uber"),
    ("BOLT", MatchField.MERCHANT, CAT_TAXI, 22, "Bolt"),
    ("LIME", MatchField.MERCHANT, CAT_TAXI, 22, "Lime micromobility"),
    ("LIFTAGO", MatchField.MERCHANT, CAT_TAXI, 22, "Liftago"),
    ("REGIOJET", MatchField.MERCHANT, CAT_PUBLIC_TRANSIT, 22, "RegioJet"),
    ("CD.CZ", MatchField.MERCHANT, CAT_PUBLIC_TRANSIT, 22, "CD"),
    ("ČD ", MatchField.DESCRIPTION, CAT_PUBLIC_TRANSIT, 22, "CD train"),
    # Food out / delivery
    ("STARBUCKS", MatchField.MERCHANT, CAT_COFFEE, 28, "Starbucks"),
    ("TIM HORTONS", MatchField.MERCHANT, CAT_COFFEE, 26, "Tim Hortons"),
    ("BISTROT", MatchField.MERCHANT, CAT_RESTAURANTS, 26, "Bistrot"),
    ("EMPIK", MatchField.MERCHANT, CAT_SHOP_GENERAL, 26, "Empik"),
    ("MCDONALD", MatchField.MERCHANT, CAT_RESTAURANTS, 28, "McD"),
    ("KFC", MatchField.MERCHANT, CAT_RESTAURANTS, 28, "KFC"),
    ("WOLT", MatchField.MERCHANT, CAT_RESTAURANTS, 28, "Wolt"),
    ("FOODORA", MatchField.MERCHANT, CAT_RESTAURANTS, 28, "Foodora"),
    ("DAMENU", MatchField.MERCHANT, CAT_RESTAURANTS, 28, "DameJidlo"),
    ("DAMEJIDLO", MatchField.MERCHANT, CAT_RESTAURANTS, 28, "DameJidlo name"),
    ("DELIVEROO", MatchField.MERCHANT, CAT_RESTAURANTS, 28, "Deliveroo"),
    ("HOXTON", MatchField.MERCHANT, CAT_RESTAURANTS, 26, "Hoxton"),
    ("ILUNCH", MatchField.MERCHANT, CAT_RESTAURANTS, 26, "ilunch"),
    ("BON FRESH", MatchField.MERCHANT, CAT_RESTAURANTS, 26, "BON Fresh ramen"),
    ("RESTAURACE", MatchField.MERCHANT, CAT_RESTAURANTS, 28, "restaurace"),
    # Subscriptions (software / digital services)
    ("SPOTIFY", MatchField.MERCHANT, CAT_SPOTIFY, 15, "Spotify"),
    ("NETFLIX", MatchField.MERCHANT, CAT_STREAMING, 15, "Netflix"),
    ("YOUTUBE", MatchField.MERCHANT, CAT_STREAMING, 15, "YouTube"),
    ("DISNEY", MatchField.MERCHANT, CAT_STREAMING, 15, "Disney"),
    ("APPLE.COM/BILL", MatchField.DESCRIPTION, CAT_SOFTWARE, 14, "Apple sub bill"),
    ("APPLE", MatchField.MERCHANT, CAT_SOFTWARE, 18, "Apple subscription"),
    ("GOOGLE *", MatchField.DESCRIPTION, CAT_SOFTWARE, 16, "Google"),
    ("MICROSOFT", MatchField.MERCHANT, CAT_SOFTWARE, 16, "Microsoft"),
    ("OPENAI", MatchField.MERCHANT, CAT_SOFTWARE, 14, "OpenAI sub"),
    ("CHATGPT", MatchField.MERCHANT, CAT_SOFTWARE, 14, "ChatGPT sub"),
    ("GITHUB", MatchField.MERCHANT, CAT_SOFTWARE, 16, "GitHub"),
    ("TWITTER", MatchField.MERCHANT, CAT_SOFTWARE, 16, "Twitter/X sub"),
    ("X.COM", MatchField.MERCHANT, CAT_SOFTWARE, 16, "X.com sub"),
    # Health + fitness
    ("ALLIANZ", MatchField.MERCHANT, CAT_INSURANCE, 18, "Allianz"),
    ("VZP", MatchField.MERCHANT, CAT_INSURANCE, 18, "VZP"),
    (" generalli", MatchField.MERCHANT, CAT_INSURANCE, 18, "Generali"),
    ("DR.MAX", MatchField.MERCHANT, CAT_PHARMACY, 24, "Dr.Max"),
    ("BENU", MatchField.MERCHANT, CAT_PHARMACY, 24, "Benu"),
    ("ACTIVE PEOPLE", MatchField.MERCHANT, CAT_FITNESS, 16, "Active People fitness"),
    ("GYM", MatchField.MERCHANT, CAT_FITNESS, 22, "gym"),
    ("FITNESS", MatchField.MERCHANT, CAT_FITNESS, 20, "fitness"),
    ("CROSSFIT", MatchField.MERCHANT, CAT_FITNESS, 18, "crossfit"),
    ("PILATES", MatchField.MERCHANT, CAT_FITNESS, 20, "pilates"),
    ("YOGA", MatchField.MERCHANT, CAT_FITNESS, 22, "yoga"),
    ("FORM FACTORY", MatchField.MERCHANT, CAT_FITNESS, 16, "Form Factory"),
    ("WORLD CLASS", MatchField.MERCHANT, CAT_FITNESS, 16, "World Class gym"),
    ("ANYTIME FITNESS", MatchField.MERCHANT, CAT_FITNESS, 16, "Anytime Fitness"),
    ("BESTFIT", MatchField.MERCHANT, CAT_FITNESS, 16, "Bestfit Club"),
    ("BEST FIT", MatchField.MERCHANT, CAT_FITNESS, 16, "Best Fit"),
    # Housing / utilities
    ("ČEZ", MatchField.MERCHANT, CAT_UTILITIES, 18, "CEZ"),
    ("CEZ", MatchField.MERCHANT, CAT_UTILITIES, 18, "CEZ"),
    ("PRE ", MatchField.MERCHANT, CAT_UTILITIES, 18, "PRE"),
    ("T-MOBILE", MatchField.MERCHANT, CAT_INTERNET, 18, "T-Mobile"),
    ("VODAFONE", MatchField.MERCHANT, CAT_INTERNET, 18, "Vodafone"),
    ("O2 ", MatchField.MERCHANT, CAT_INTERNET, 18, "O2"),
    ("UPC", MatchField.MERCHANT, CAT_INTERNET, 18, "UPC"),
    ("NÁJEM", MatchField.DESCRIPTION, CAT_RENT, 17, "najem"),
    ("NAJEM", MatchField.DESCRIPTION, CAT_RENT, 17, "najem"),
    ("RENT", MatchField.DESCRIPTION, CAT_RENT, 17, "rent"),
    # Shopping
    ("CZC.CZ", MatchField.MERCHANT, CAT_ELECTRONICS, 26, "CZC"),
    ("AMAZON", MatchField.MERCHANT, CAT_SHOP_GENERAL, 26, "Amazon"),
    ("ALIEXPRESS", MatchField.MERCHANT, CAT_SHOP_GENERAL, 26, "AliExpress"),
    ("ZALANDO", MatchField.MERCHANT, CAT_CLOTHING, 26, "Zalando"),
    ("H&M", MatchField.MERCHANT, CAT_CLOTHING, 26, "HM"),
    ("RESERVED", MatchField.MERCHANT, CAT_CLOTHING, 26, "Reserved"),
    ("BARBER", MatchField.MERCHANT, CAT_SHOP_GENERAL, 26, "barber personal care"),
    ("HELL'S BARBER", MatchField.MERCHANT, CAT_SHOP_GENERAL, 20, "Hells Barber"),
    ("HELLS BARBER", MatchField.MERCHANT, CAT_SHOP_GENERAL, 20, "Hells Barber ascii"),
    # Cash
    ("Cash withdrawal", MatchField.DESCRIPTION, CAT_CASH_WITHDRAWAL, 14, "cash withdrawal"),
    ("ATM", MatchField.DESCRIPTION, CAT_CASH_WITHDRAWAL, 20, "ATM"),
    # Business — 3D print materials / tools
    ("PRUSAMENT", MatchField.MERCHANT, CAT_BIZ_MATERIALS, 12, "Prusament filament"),
    ("PRUSA", MatchField.MERCHANT, CAT_BIZ_MATERIALS, 14, "Prusa Research"),
    ("BAMBULAB", MatchField.MERCHANT, CAT_BIZ_MATERIALS, 12, "Bambu Lab"),
    ("BAMBU LAB", MatchField.MERCHANT, CAT_BIZ_MATERIALS, 12, "Bambu Lab spaced"),
    ("BAMBU", MatchField.MERCHANT, CAT_BIZ_MATERIALS, 16, "Bambu"),
    ("ESUN", MatchField.MERCHANT, CAT_BIZ_MATERIALS, 14, "eSUN filament"),
    ("SUNLU", MatchField.MERCHANT, CAT_BIZ_MATERIALS, 14, "Sunlu filament"),
    ("POLYMAKER", MatchField.MERCHANT, CAT_BIZ_MATERIALS, 14, "Polymaker"),
    ("FILAMENT", MatchField.DESCRIPTION, CAT_BIZ_MATERIALS, 18, "filament keyword"),
    ("3D PRINT", MatchField.DESCRIPTION, CAT_BIZ_MATERIALS, 18, "3d print"),
    ("ELEGOO", MatchField.MERCHANT, CAT_BIZ_TOOLS, 14, "Elegoo printer"),
    ("ANYCUBIC", MatchField.MERCHANT, CAT_BIZ_TOOLS, 14, "Anycubic printer"),
    ("RESIN", MatchField.DESCRIPTION, CAT_BIZ_MATERIALS, 22, "resin keyword"),
    # Entertainment
    ("CINEMA", MatchField.MERCHANT, CAT_GOING_OUT, 30, "Cinema"),
    ("CINESTAR", MatchField.MERCHANT, CAT_GOING_OUT, 30, "Cinestar"),
    # Investments / transfers
    ("ETORO", MatchField.DESCRIPTION, CAT_BROKER, 14, "eToro"),
    ("REVOLUT.*STOCK", MatchField.DESCRIPTION, CAT_BROKER, 14, "rev stocks"),
    # Cash legs of Revolut crypto buys/sells (Current ↔ Digital Assets pot)
    (
        "Revolut Digital Assets Europe Ltd",
        MatchField.DESCRIPTION,
        CAT_CRYPTO_FUND,
        6,
        "rev digital assets crypto pot internal",
    ),
    ("CRYPTO", MatchField.DESCRIPTION, CAT_CRYPTO_FUND, 35, "crypto loose"),
    ("Transfer to", MatchField.DESCRIPTION, CAT_EXTERNAL_XFER, 40, "rev transfer"),
    ("To main account", MatchField.DESCRIPTION, CAT_INTERNAL, 9, "rev internal"),
    ("Between own accounts", MatchField.DESCRIPTION, CAT_INTERNAL, 8, "own accounts"),
    # Fees
    ("CUSTODY FEE", MatchField.DESCRIPTION, CAT_BANK_FEES, 13, "custody"),
    ("Card fee", MatchField.DESCRIPTION, CAT_BANK_FEES, 13, "card fee"),
    ("Poplatek", MatchField.DESCRIPTION, CAT_BANK_FEES, 13, "poplatek"),
    # Income
    ("Salary", MatchField.DESCRIPTION, CAT_SALARY, 10, "salary"),
    ("Mzda", MatchField.DESCRIPTION, CAT_SALARY, 10, "mzda"),
    ("WAGE", MatchField.DESCRIPTION, CAT_SALARY, 10, "wage"),
    ("Payroll", MatchField.DESCRIPTION, CAT_SALARY, 10, "payroll"),
    # Own-account Raiffeisen ↔ Revolut (NOT living spend)
    # Note: personal-name keywords intentionally omitted (Gauntlet PII policy).
    ("Sent from Revolut", MatchField.ORIGINAL_DESCRIPTION, CAT_INTERNAL, 5, "rb from revolut internal"),
    ("Single payment — Revolut", MatchField.DESCRIPTION, CAT_INTERNAL, 5, "rb single to revolut internal"),
    ("Revolut transfer", MatchField.DESCRIPTION, CAT_INTERNAL, 6, "rb revolut transfer internal"),
    ("Transfer to my", MatchField.ORIGINAL_DESCRIPTION, CAT_INTERNAL, 6, "rb transfer to my revolut"),
    # Card top-up: Raiffeisen charged Revolut**card for funding Revolut balance
    ("Revolut**", MatchField.DESCRIPTION, CAT_INTERNAL, 5, "rb revolut card topup internal"),
    ("REVOLUT**", MatchField.DESCRIPTION, CAT_INTERNAL, 5, "rb revolut card topup upper"),
    ("Card payment — Revolut", MatchField.DESCRIPTION, CAT_INTERNAL, 5, "rb card payment revolut topup"),
    # Peer / true external (keep after own-account rules)
    ("Outgoing instant payment", MatchField.DESCRIPTION, CAT_EXTERNAL_XFER, 15, "instant pay"),
    ("Revolut Bank UAB", MatchField.MERCHANT, CAT_INTERNAL, 8, "revolut bank uab"),
    ("Revolut Bank UAB", MatchField.DESCRIPTION, CAT_INTERNAL, 8, "revolut bank uab desc"),
    # Vault / spare change / own multi-currency FX — NOT living spend
    ("Exchanged to", MatchField.DESCRIPTION, CAT_INTERNAL, 8, "own fx exchange internal"),
    ("Exchange to", MatchField.DESCRIPTION, CAT_INTERNAL, 8, "own fx exchange internal 2"),
    ("Pocket Withdrawal", MatchField.DESCRIPTION, CAT_INTERNAL, 8, "vault to personal internal"),
    ("To pocket", MatchField.DESCRIPTION, CAT_INTERNAL, 8, "pocket vault internal"),
    ("Purchase vault", MatchField.DESCRIPTION, CAT_INTERNAL, 8, "purchase vault internal"),
    ("from vault", MatchField.DESCRIPTION, CAT_INTERNAL, 9, "from vault internal"),
    ("vault to", MatchField.DESCRIPTION, CAT_INTERNAL, 9, "vault to internal"),
    ("from CZK", MatchField.DESCRIPTION, CAT_INTERNAL, 45, "pocket vault loose"),
    ("To investment account", MatchField.DESCRIPTION, CAT_BROKER, 12, "to investment"),
    # Debt
    ("Loan repayment", MatchField.DESCRIPTION, CAT_LOANS, 12, "loan repayment"),
    ("Loan interest", MatchField.DESCRIPTION, CAT_LOANS, 12, "loan interest"),
    ("Credit instalment", MatchField.DESCRIPTION, CAT_LOANS, 12, "credit instalment"),
    ("RePujcka", MatchField.DESCRIPTION, CAT_LOANS, 12, "repujcka"),
    ("Minutova pujcka", MatchField.DESCRIPTION, CAT_LOANS, 12, "minutova"),
    ("pujcka", MatchField.DESCRIPTION, CAT_LOANS, 14, "pujcka"),
    # Travel
    ("Etihad", MatchField.MERCHANT, CAT_PUBLIC_TRANSIT, 20, "airline as transport"),
    ("Airlines", MatchField.MERCHANT, CAT_PUBLIC_TRANSIT, 22, "airlines"),
    ("Ryanair", MatchField.MERCHANT, CAT_PUBLIC_TRANSIT, 20, "ryanair"),
    ("Wizz", MatchField.MERCHANT, CAT_PUBLIC_TRANSIT, 20, "wizz"),
    ("Hotel", MatchField.MERCHANT, CAT_GOING_OUT, 28, "hotel"),
    ("Booking.com", MatchField.MERCHANT, CAT_GOING_OUT, 28, "booking"),
    ("Airbnb", MatchField.MERCHANT, CAT_GOING_OUT, 28, "airbnb"),
]


def _rule_key(field: MatchField, value: str, category_id: UUID) -> str:
    return f"{field.value}|{value.lower().strip()}|{category_id}"


# Needles / notes that encode personal lifestyle (moto, 3D print, local haunts).
# Starter install skips these so new accounts get a generic pack only.
_PERSONAL_STARTER_FRAGMENTS: frozenset[str] = frozenset(
    {
        "harley",
        "ducati",
        "yamaha",
        "honda moto",
        "4ride",
        "chrome burnout",
        "hein gericke",
        "moto",
        "motorcycl",
        "prusa",
        "prusament",
        "bambu",
        "filament",
        "elegoo",
        "anycubic",
        "esun",
        "sunlu",
        "polymaker",
        "3d print",
        "resin",
        "hell's barber",
        "hells barber",
        "artic bakehouse",
        "bakehouse",
        "hoxton",
        "ilunch",
        "bon fresh",
        "active people",
        "form factory",
        "world class",
        "anytime fitness",
        "bestfit",
        "best fit",
        "moto fuel",
        "moto_",
        "biz_",
        "business",
        "self-education",
        "cezary",
    }
)

# Lifestyle category targets — never install via generic starter.
_PERSONAL_STARTER_CATEGORY_IDS: frozenset[UUID] = frozenset()


def _remap_generic_starter_category(cat_id: UUID) -> UUID | None:
    """
    Map lifestyle category targets to neutral ones for starter install.
    Returns None if the rule should be skipped entirely.
    """
    from backend.schema.default_categories import (
        CAT_BIZ_MATERIALS,
        CAT_BIZ_TOOLS,
        CAT_BIZ_SHIPPING,
        CAT_BIZ_OTHER,
        CAT_BIZ_INCOME,
        CAT_FUEL_CAR,
        CAT_MOTORCYCLING,
        CAT_MOTO_FUEL,
        CAT_MOTO_GEAR,
        CAT_MOTO_SERVICE,
        CAT_MOTO_INSURANCE,
        CAT_MOTO_OTHER,
    )

    if cat_id == CAT_MOTO_FUEL:
        return CAT_FUEL_CAR
    personal_skip = {
        CAT_BIZ_MATERIALS,
        CAT_BIZ_TOOLS,
        CAT_BIZ_SHIPPING,
        CAT_BIZ_OTHER,
        CAT_BIZ_INCOME,
        CAT_MOTORCYCLING,
        CAT_MOTO_GEAR,
        CAT_MOTO_SERVICE,
        CAT_MOTO_INSURANCE,
        CAT_MOTO_OTHER,
    }
    if cat_id in personal_skip:
        return None
    return cat_id


def _is_personal_starter_rule(
    needle: str,
    notes: str,
    cat_id: UUID,
) -> bool:
    """True when needle/notes encode owner lifestyle (after category remap)."""
    blob = f"{needle} {notes}".lower()
    # Fuel brands are generic — keep if remapped to car fuel
    if any(
        f in blob
        for f in (
            "shell",
            "omv",
            "benzina",
            "orlen",
            "eurooil",
            "tank ono",
            "amic",
            "hunsgas",
        )
    ):
        return False
    if any(frag in blob for frag in _PERSONAL_STARTER_FRAGMENTS):
        return True
    return False


def bootstrap_rules_from_data(
    repo: SheetsRepository,
    *,
    also_apply: bool = False,
    public_demo: bool = False,
) -> dict[str, Any]:
    """
    Ensure categories, add generic keyword + merchant-derived rules (no duplicates),
    optionally apply to blanks & Other.

    public_demo=True uses public category ensure (no owner self-education rule).
    """
    if public_demo:
        from backend.schema.demo_public import ensure_public_demo_categories

        ensure_stats = ensure_public_demo_categories(repo)
    else:
        ensure_stats = ensure_default_categories(repo)
    existing_rules = [
        r for r in repo.list_rows("CategoryRules") if isinstance(r, CategoryRule) and not r.archived
    ]
    seen = {
        _rule_key(r.match_field, r.match_value, r.category_id): r for r in existing_rules
    }
    now = utc_now()
    created: list[CategoryRule] = []
    skipped_personal = 0

    # 1) Keyword pack (generic only)
    for needle, field, cat_id, prio, notes in _KEYWORD_RULES:
        # Skip loose CRYPTO keyword that is too aggressive for match_type contains on description
        if needle == "CRYPTO":
            continue
        remapped = _remap_generic_starter_category(cat_id)
        if remapped is None:
            skipped_personal += 1
            continue
        cat_id = remapped
        if _is_personal_starter_rule(needle, notes, cat_id):
            skipped_personal += 1
            continue
        key = _rule_key(field, needle, cat_id)
        if key in seen:
            continue
        mt = MatchType.CONTAINS
        if needle.startswith("REVOLUT"):
            mt = MatchType.REGEX
        rule = CategoryRule(
            id=uuid4(),
            priority=prio,
            match_field=field,
            match_type=mt,
            match_value=needle,
            category_id=cat_id,
            set_internal_transfer=("internal" in notes.lower() or "own account" in notes.lower()),
            institution_scope=None,
            is_active=True,
            notes=f"bootstrap:{notes}",
            created_at=now,
            updated_at=now,
        )
        # Fix internal transfer flags
        if cat_id == CAT_INTERNAL:
            rule = rule.model_copy(update={"set_internal_transfer": True})
        created.append(rule)
        seen[key] = rule

    # 2) Scan top merchants from uncategorized expenses → map via keywords in merchant name
    fx = build_fx_service(repo)
    cats = {c.id: c for c in repo.list_rows("Categories") if isinstance(c, Category)}
    merchant_spend: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for tx in repo.list_rows("Transactions"):
        if not isinstance(tx, Transaction) or tx.archived or tx.is_internal_transfer:
            continue
        if tx.amount >= 0:
            continue
        label = (tx.merchant or tx.counterparty_name or tx.description or "").strip()
        if len(label) < 3:
            continue
        # Prefer uncategorized for discovery, but include all for mapping strength
        usd = tx_signed_usd(tx, fx)
        if usd is None or usd >= 0:
            continue
        merchant_spend[label] += abs(usd)

    top = sorted(merchant_spend.items(), key=lambda x: x[1], reverse=True)[:80]
    mapped_merchants = 0
    for label, _spend in top:
        cat_id = _map_merchant_label(label)
        if cat_id is None:
            continue
        remapped = _remap_generic_starter_category(cat_id)
        if remapped is None:
            skipped_personal += 1
            continue
        cat_id = remapped
        if _is_personal_starter_rule(label, "merchant", cat_id):
            skipped_personal += 1
            continue
        key = _rule_key(MatchField.MERCHANT, label, cat_id)
        if key in seen:
            continue
        # Use contains with a stable token (first significant word or full label if short)
        needle = label if len(label) <= 40 else label[:40]
        rule = CategoryRule(
            id=uuid4(),
            priority=50,
            match_field=MatchField.MERCHANT,
            match_type=MatchType.CONTAINS,
            match_value=needle,
            category_id=cat_id,
            set_internal_transfer=False,
            institution_scope=None,
            is_active=True,
            notes=f"bootstrap:merchant:{label[:60]}",
            created_at=now,
            updated_at=now,
        )
        created.append(rule)
        seen[key] = rule
        mapped_merchants += 1

    if created:
        repo.upsert_rows("CategoryRules", created)

    apply_stats = None
    if also_apply:
        apply_stats = apply_rules_fill_blanks(repo)
    else:
        cache_invalidate()

    return {
        "ensure": ensure_stats,
        "rules_created": len(created),
        "rules_skipped_personal": skipped_personal,
        "rules_total_active": len(
            [
                r
                for r in repo.list_rows("CategoryRules")
                if isinstance(r, CategoryRule) and r.is_active and not r.archived
            ]
        ),
        "merchants_mapped": mapped_merchants,
        "top_merchants_scanned": len(top),
        "apply": apply_stats,
    }


def _map_merchant_label(label: str) -> UUID | None:
    u = label.upper()
    checks: list[tuple[str, UUID]] = [
        ("BILLA", CAT_GROCERIES),
        ("LIDL", CAT_GROCERIES),
        ("ALBERT", CAT_GROCERIES),
        ("TESCO", CAT_GROCERIES),
        ("KAUFLAND", CAT_GROCERIES),
        ("PENNY", CAT_GROCERIES),
        ("ROHL", CAT_GROCERIES),
        ("KOSIK", CAT_GROCERIES),
        ("KOŠÍK", CAT_GROCERIES),
        ("POTRAVINY", CAT_GROCERIES),
        ("BAKEHOUSE", CAT_GROCERIES),
        ("PEKARNA", CAT_GROCERIES),
        ("PEKÁRNA", CAT_GROCERIES),
        ("SHELL", CAT_FUEL_CAR),
        ("OMV", CAT_FUEL_CAR),
        ("BENZINA", CAT_FUEL_CAR),
        ("MOL", CAT_FUEL_CAR),
        ("ORLEN", CAT_FUEL_CAR),
        ("UBER", CAT_TAXI),
        ("BOLT", CAT_TAXI),
        ("LIME", CAT_TAXI),
        ("LIFTAGO", CAT_TAXI),
        ("SPOTIFY", CAT_SPOTIFY),
        ("NETFLIX", CAT_STREAMING),
        ("ALZA", CAT_SHOP_GENERAL),
        ("AMAZON", CAT_SHOP_GENERAL),
        ("ALIEXPRESS", CAT_SHOP_GENERAL),
        ("ZALANDO", CAT_CLOTHING),
        ("ALLIANZ", CAT_INSURANCE),
        ("DR.MAX", CAT_PHARMACY),
        ("DR MAX", CAT_PHARMACY),
        ("BENU", CAT_PHARMACY),
        ("MOTO", CAT_MOTORCYCLING),
        ("MOTORRAD", CAT_MOTO_GEAR),
        ("HEIN GERICKE", CAT_MOTO_GEAR),
        ("ATM", CAT_CASH_WITHDRAWAL),
        ("CASH WITHDRAWAL", CAT_CASH_WITHDRAWAL),
        ("REVOLUT BANK", CAT_INTERNAL),
        ("POCKET WITHDRAWAL", CAT_INTERNAL),
        ("EXCHANGED TO", CAT_INTERNAL),
        ("PURCHASE VAULT", CAT_INTERNAL),
        ("HOXTON", CAT_RESTAURANTS),
        ("BARBER", CAT_SHOP_GENERAL),
        ("OČKOVAC", CAT_MEDICAL),
        ("OCKOVAC", CAT_MEDICAL),
        ("ATODA", CAT_MEDICAL),
        ("TWITTER", CAT_SOFTWARE),
        ("X.COM", CAT_SOFTWARE),
        ("OPENAI", CAT_SOFTWARE),
        ("APPLE", CAT_SOFTWARE),
        ("WOLT", CAT_RESTAURANTS),
        ("FOODORA", CAT_RESTAURANTS),
        ("DAMEJIDLO", CAT_RESTAURANTS),
        ("DELIVEROO", CAT_RESTAURANTS),
        ("STARBUCKS", CAT_COFFEE),
        ("MCDONALD", CAT_RESTAURANTS),
        ("PID", CAT_PUBLIC_TRANSIT),
        ("LÍTAČKA", CAT_PUBLIC_TRANSIT),
        ("LITACKA", CAT_PUBLIC_TRANSIT),
        ("REGIOJET", CAT_PUBLIC_TRANSIT),
        ("ETORO", CAT_BROKER),
        ("IKEA", CAT_SHOP_GENERAL),
        ("H&M", CAT_CLOTHING),
        ("H & M", CAT_CLOTHING),
        ("PHARMAC", CAT_PHARMACY),
        ("LEKARNA", CAT_PHARMACY),
        ("LÉKÁRNA", CAT_PHARMACY),
        ("NEMOCNIC", CAT_MEDICAL),
        ("HOSPITAL", CAT_MEDICAL),
        ("ACTIVE PEOPLE", CAT_FITNESS),
        ("FITNESS", CAT_FITNESS),
        ("FORM FACTORY", CAT_FITNESS),
        ("PRUSAMENT", CAT_BIZ_MATERIALS),
        ("PRUSA", CAT_BIZ_MATERIALS),
        ("BAMBU", CAT_BIZ_MATERIALS),
        ("FILAMENT", CAT_BIZ_MATERIALS),
        ("ELEGOO", CAT_BIZ_TOOLS),
        ("ANYCUBIC", CAT_BIZ_TOOLS),
    ]
    for needle, cat in checks:
        if needle in u:
            return cat
    return None


_TARGET_PCT = 90.0
_AMBER_PCT = 70.0


def _uncat_match_key(tx: Transaction) -> tuple[str, str]:
    """Field + value used for queue matching (prefer merchant)."""
    m = (tx.merchant or "").strip()
    if m:
        return "merchant", m
    c = (tx.counterparty_name or "").strip()
    if c:
        return "counterparty_name", c
    d = (tx.description or "").strip()
    if d:
        return "description", d[:120]
    o = (tx.original_description or "").strip()
    if o:
        return "original_description", o[:120]
    return "description", "Unknown"


def _window_coverage(
    txs: list[Transaction],
    cats: dict[UUID, Category],
    fx: Any,
    *,
    start: date,
    end: date,
) -> dict[str, Any]:
    total = Decimal("0")
    categorized = Decimal("0")
    by_domain: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    # key = (match_field, match_value)
    uncat_merchants: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    uncat_counts: dict[tuple[str, str], int] = defaultdict(int)

    for tx in txs:
        if tx.archived or tx.is_internal_transfer:
            continue
        if tx.booking_date < start or tx.booking_date > end:
            continue
        if tx.amount >= 0:
            continue
        usd = tx_signed_usd(tx, fx)
        if usd is None or usd >= 0:
            continue
        exp = abs(usd)
        total += exp
        cat = cats.get(tx.category_id) if tx.category_id else None
        if cat is None or cat.life_domain.value == "Other":
            field, value = _uncat_match_key(tx)
            uncat_merchants[(field, value)] += exp
            uncat_counts[(field, value)] += 1
        else:
            categorized += exp
            by_domain[cat.life_domain.value] += exp

    pct = float((categorized / total) * 100) if total > 0 else 0.0
    if pct >= _TARGET_PCT:
        status = "on_target"
    elif pct >= _AMBER_PCT:
        status = "stretch"
    else:
        status = "below_target"
    uncat_usd = total - categorized
    top_rows = sorted(uncat_merchants.items(), key=lambda x: x[1], reverse=True)[:15]
    return {
        "expense_usd_total": str(total.quantize(Decimal("0.01"))),
        "expense_usd_categorized": str(categorized.quantize(Decimal("0.01"))),
        "uncategorized_expense_usd": str(uncat_usd.quantize(Decimal("0.01"))),
        "coverage_pct": pct,
        "status": status,
        "by_domain": [
            {"name": k, "amount_usd": str(v.quantize(Decimal("0.01")))}
            for k, v in sorted(by_domain.items(), key=lambda x: x[1], reverse=True)
        ],
        "top_uncategorized_merchants": [
            {
                "label": value,
                "match_field": field,
                "match_value": value,
                "amount_usd": str(amt.quantize(Decimal("0.01"))),
                "tx_count": uncat_counts[(field, value)],
            }
            for (field, value), amt in top_rows
        ],
        "_merchant_map": uncat_merchants,
        "_merchant_counts": uncat_counts,
    }


def coverage_stats(repo: SheetsRepository, *, days: int = 180) -> dict[str, Any]:
    """Expense USD coverage for last N days (excl. internal transfers)."""
    fx = build_fx_service(repo)
    cats = {
        c.id: c
        for c in repo.list_rows("Categories")
        if isinstance(c, Category) and not c.archived
    }
    today = date.today()
    txs = [t for t in repo.list_rows("Transactions") if isinstance(t, Transaction)]
    primary = _window_coverage(
        txs, cats, fx, start=today - timedelta(days=days - 1), end=today
    )
    w30 = _window_coverage(txs, cats, fx, start=today - timedelta(days=29), end=today)
    # Drop private maps from public payload
    top = primary["top_uncategorized_merchants"]
    return {
        "days": days,
        "expense_usd_total": primary["expense_usd_total"],
        "expense_usd_categorized": primary["expense_usd_categorized"],
        "uncategorized_expense_usd": primary["uncategorized_expense_usd"],
        "coverage_pct": primary["coverage_pct"],
        "target_pct": _TARGET_PCT,
        "amber_pct": _AMBER_PCT,
        "status": primary["status"],
        "progress_note": (
            f"Target {_TARGET_PCT:.0f}% non-Other expense coverage "
            f"(amber floor {_AMBER_PCT:.0f}%)."
        ),
        "by_domain": primary["by_domain"],
        "top_uncategorized_merchants": top,
        "windows": {
            "30d": {
                "coverage_pct": w30["coverage_pct"],
                "status": w30["status"],
                "expense_usd_total": w30["expense_usd_total"],
                "uncategorized_expense_usd": w30["uncategorized_expense_usd"],
            },
            "180d": {
                "coverage_pct": primary["coverage_pct"],
                "status": primary["status"],
                "expense_usd_total": primary["expense_usd_total"],
                "uncategorized_expense_usd": primary["uncategorized_expense_usd"],
            },
        },
        "categories_count": len(cats),
        "rules_count": len(
            [
                r
                for r in repo.list_rows("CategoryRules")
                if isinstance(r, CategoryRule) and r.is_active and not r.archived
            ]
        ),
    }


def _normalize_label(s: str) -> str:
    return " ".join((s or "").lower().split())


def _token_set(s: str) -> set[str]:
    return {t for t in _normalize_label(s).replace("/", " ").split() if len(t) >= 3}


def _build_category_affinity(
    txs: list[Transaction],
    cats: dict[UUID, Category],
) -> dict[str, dict[UUID, int]]:
    token_hits: dict[str, dict[UUID, int]] = defaultdict(lambda: defaultdict(int))
    for t in txs:
        if t.archived or t.is_internal_transfer or t.category_id is None:
            continue
        if t.category_id not in cats:
            continue
        labels = [t.merchant or "", t.counterparty_name or "", (t.description or "")[:80]]
        for lab in labels:
            for tok in _token_set(lab):
                token_hits[tok][t.category_id] += 1
        merch = _normalize_label(t.merchant or "")
        if merch and len(merch) >= 3:
            token_hits[f"exact:{merch}"][t.category_id] += 2
    return token_hits  # type: ignore[return-value]


def _suggest_category_for_label(
    label: str,
    affinity: dict[str, dict[UUID, int]],
    cats: dict[UUID, Category],
) -> tuple[UUID | None, float, str | None]:
    scores: dict[UUID, float] = defaultdict(float)
    exact_key = f"exact:{_normalize_label(label)}"
    if exact_key in affinity:
        for cid, n in affinity[exact_key].items():
            scores[cid] += float(n) * 3.0
    for tok in _token_set(label):
        if tok not in affinity:
            continue
        for cid, n in affinity[tok].items():
            scores[cid] += float(n)
    if not scores:
        return None, 0.0, None
    best_cid, best = max(scores.items(), key=lambda x: x[1])
    total = sum(scores.values()) or 1.0
    conf = min(1.0, best / total)
    if best < 2:
        return None, conf, None
    name = cats[best_cid].name if best_cid in cats else None
    return best_cid, conf, name


def merchant_queue(
    repo: SheetsRepository, *, days: int = 180, limit: int = 40
) -> dict[str, Any]:
    """Top uncategorized labels for review queue (with match field for apply)."""
    fx = build_fx_service(repo)
    cats = {
        c.id: c
        for c in repo.list_rows("Categories")
        if isinstance(c, Category) and not c.archived
    }
    today = date.today()
    start = today - timedelta(days=days - 1)
    all_txs = [t for t in repo.list_rows("Transactions") if isinstance(t, Transaction)]
    w = _window_coverage(all_txs, cats, fx, start=start, end=today)
    affinity = _build_category_affinity(all_txs, cats)
    full = sorted(w["_merchant_map"].items(), key=lambda x: x[1], reverse=True)[:limit]
    items = []
    for (field, value), amt in full:
        sug_id, conf, sug_name = _suggest_category_for_label(value, affinity, cats)
        items.append(
            {
                "label": value,
                "match_field": field,
                "match_value": value,
                "amount_usd": str(amt.quantize(Decimal("0.01"))),
                "tx_count": w["_merchant_counts"][(field, value)],
                "suggested_category_id": str(sug_id) if sug_id else None,
                "suggested_category_name": sug_name,
                "suggestion_confidence": round(conf, 3) if sug_id else None,
            }
        )
    return {
        "days": days,
        "items": items,
        "coverage_pct": w["coverage_pct"],
    }


def rule_suggestions(
    repo: SheetsRepository, *, days: int = 180, limit: int = 20
) -> dict[str, Any]:
    """Ranked residual rule proposals (heuristics; human apply only)."""
    fx = build_fx_service(repo)
    cats = {
        c.id: c
        for c in repo.list_rows("Categories")
        if isinstance(c, Category) and not c.archived
    }
    rules = [
        r
        for r in repo.list_rows("CategoryRules")
        if isinstance(r, CategoryRule) and r.is_active and not r.archived
    ]
    existing_values = {
        (
            (
                r.match_field.value
                if hasattr(r.match_field, "value")
                else str(r.match_field)
            ).lower(),
            _normalize_label(r.match_value),
        )
        for r in rules
    }
    today = date.today()
    start = today - timedelta(days=days - 1)
    all_txs = [t for t in repo.list_rows("Transactions") if isinstance(t, Transaction)]
    w = _window_coverage(all_txs, cats, fx, start=start, end=today)
    affinity = _build_category_affinity(all_txs, cats)

    last_seen: dict[tuple[str, str], date] = {}
    for t in all_txs:
        if t.archived or t.is_internal_transfer:
            continue
        cat = cats.get(t.category_id) if t.category_id else None
        if cat is not None and cat.name.lower() not in {"other", "uncategorized"}:
            continue
        field, value = "merchant", (t.merchant or "").strip()
        if not value:
            field, value = "description", (t.description or "").strip()[:80]
        if not value:
            continue
        key = (field, value)
        if key not in last_seen or t.booking_date > last_seen[key]:
            last_seen[key] = t.booking_date

    scored: list[dict[str, Any]] = []
    for (field, value), amt in w["_merchant_map"].items():
        if (field.lower(), _normalize_label(value)) in existing_values:
            continue
        count = int(w["_merchant_counts"][(field, value)])
        amt_f = float(amt)
        recency_days = 999
        if (field, value) in last_seen:
            recency_days = max(0, (today - last_seen[(field, value)]).days)
        recency_score = max(0.0, 1.0 - (recency_days / max(days, 1)))
        sug_id, conf, sug_name = _suggest_category_for_label(value, affinity, cats)
        score = (
            (amt_f ** 0.5) * 2.0
            + count * 1.5
            + recency_score * 10.0
            + (conf * 15.0 if sug_id else 0.0)
        )
        reason = f"High residual spend ({count} tx)"
        if sug_name:
            reason += f"; similar to {sug_name!r}"
        scored.append(
            {
                "label": value,
                "match_field": field,
                "match_type": "contains",
                "match_value": value[:120],
                "amount_usd": str(amt.quantize(Decimal("0.01"))),
                "tx_count": count,
                "last_seen": last_seen.get((field, value), today).isoformat(),
                "recency_days": recency_days,
                "score": round(score, 2),
                "suggested_category_id": str(sug_id) if sug_id else None,
                "suggested_category_name": sug_name,
                "suggestion_confidence": round(conf, 3) if sug_id else None,
                "reason": reason,
            }
        )
    scored.sort(key=lambda x: x["score"], reverse=True)
    return {
        "days": days,
        "coverage_pct": w["coverage_pct"],
        "items": scored[: max(1, min(limit, 50))],
    }


def apply_merchant_queue_item(
    repo: SheetsRepository,
    *,
    label: str,
    category_id: UUID,
    match_field: str | None = None,
    match_value: str | None = None,
    make_rule: bool = True,
    also_apply: bool = True,
) -> dict[str, Any]:
    """
    Create a rule for the queue label and reclassify matching txs.

    Uses reclassify_non_override (not fill-blanks-only) so rows already tagged
    as Other / wrong category still get fixed. Match field follows how the
    queue label was built (merchant preferred, else counterparty/description).
    """
    cats = {
        c.id: c
        for c in repo.list_rows("Categories")
        if isinstance(c, Category) and not c.archived
    }
    if category_id not in cats:
        raise ValueError("category not found")

    field = (match_field or "merchant").strip()
    value = (match_value or label or "").strip()
    if not value:
        raise ValueError("match_value / label is required")
    if field not in {
        "merchant",
        "description",
        "original_description",
        "counterparty_name",
        "source_institution",
    }:
        field = "merchant"

    rule_id = None
    if make_rule:
        rule = create_rule(
            repo,
            {
                "priority": 40,
                "match_field": field,
                "match_type": "contains",
                "match_value": value[:120],
                "category_id": str(category_id),
                "notes": f"merchant-queue:{value[:40]}",
            },
        )
        rule_id = str(rule.id)

    apply_result: dict[str, Any] | None = None
    if also_apply:
        apply_result = apply_match_to_all_transactions(
            repo,
            category_id=category_id,
            match_field=field,
            match_type="contains",
            match_value=value,
            mode="reclassify_non_override",
            mark_override=False,
        )

    matched = int((apply_result or {}).get("matched") or 0)
    updated = int((apply_result or {}).get("updated") or 0)
    cache_invalidate()
    return {
        "label": value,
        "match_field": field,
        "match_value": value,
        "category_id": str(category_id),
        "rule_id": rule_id,
        "matched": matched,
        "updated": updated,
        "removed_from_queue": updated > 0,
        "apply": apply_result,
        "coverage": coverage_stats(repo, days=180),
    }


def create_category(
    repo: SheetsRepository,
    *,
    name: str,
    necessity: str,
    life_domain: str,
    parent_id: UUID | None = None,
    is_income: bool = False,
    is_transfer: bool = False,
    sort_order: int = 500,
) -> Category:
    from backend.schema.models import LifeDomain, Necessity

    now = utc_now()
    cat = Category(
        id=uuid4(),
        name=name.strip(),
        parent_id=parent_id,
        necessity=Necessity(necessity),
        life_domain=LifeDomain(life_domain),
        is_income=is_income,
        is_transfer=is_transfer,
        sort_order=sort_order,
        created_at=now,
        updated_at=now,
    )
    repo.upsert_rows("Categories", [cat])
    cache_invalidate()
    return cat


def update_category(
    repo: SheetsRepository,
    category_id: UUID,
    **fields: Any,
) -> Category:
    rows = [r for r in repo.list_rows("Categories") if isinstance(r, Category)]
    cat = next((c for c in rows if c.id == category_id), None)
    if cat is None or cat.archived:
        raise KeyError("category not found")
    from backend.schema.models import LifeDomain, Necessity

    updates: dict[str, Any] = {"updated_at": utc_now()}
    if "name" in fields and fields["name"] is not None:
        updates["name"] = str(fields["name"]).strip()
    if "parent_id" in fields:
        updates["parent_id"] = fields["parent_id"]
    if "necessity" in fields and fields["necessity"] is not None:
        updates["necessity"] = Necessity(fields["necessity"])
    if "life_domain" in fields and fields["life_domain"] is not None:
        updates["life_domain"] = LifeDomain(fields["life_domain"])
    if "is_income" in fields and fields["is_income"] is not None:
        updates["is_income"] = bool(fields["is_income"])
    if "is_transfer" in fields and fields["is_transfer"] is not None:
        updates["is_transfer"] = bool(fields["is_transfer"])
    if "sort_order" in fields and fields["sort_order"] is not None:
        updates["sort_order"] = int(fields["sort_order"])
    cat = cat.model_copy(update=updates)
    repo.upsert_rows("Categories", [cat])
    cache_invalidate()
    return cat


def archive_category(
    repo: SheetsRepository,
    category_id: UUID,
    *,
    reassign_to: UUID | None = None,
    cascade_children: bool = False,
) -> dict[str, Any]:
    rows = [r for r in repo.list_rows("Categories") if isinstance(r, Category)]
    cat = next((c for c in rows if c.id == category_id and not c.archived), None)
    if cat is None:
        raise KeyError("category not found")
    children = [c for c in rows if c.parent_id == category_id and not c.archived]
    if children and not cascade_children:
        raise ValueError(
            f"category has {len(children)} active children; pass cascade_children=true"
        )
    now = utc_now()
    archived_ids = [category_id]
    to_write: list[Category] = []
    if cascade_children:
        for ch in children:
            to_write.append(ch.model_copy(update={"archived": True, "updated_at": now}))
            archived_ids.append(ch.id)
    # reassign txs
    reassigned = 0
    tx_writes: list[Transaction] = []
    for tx in repo.list_rows("Transactions"):
        if not isinstance(tx, Transaction) or tx.archived:
            continue
        if tx.category_id in archived_ids or tx.category_id == category_id:
            if reassign_to is not None:
                tx_writes.append(
                    tx.model_copy(
                        update={
                            "category_id": reassign_to,
                            "category_override": True,
                            "updated_at": now,
                        }
                    )
                )
                reassigned += 1
            elif tx.category_id == category_id:
                tx_writes.append(
                    tx.model_copy(
                        update={
                            "category_id": None,
                            "category_override": False,
                            "updated_at": now,
                        }
                    )
                )
                reassigned += 1
    # deactivate rules
    rules_off = 0
    rule_writes: list[CategoryRule] = []
    for r in repo.list_rows("CategoryRules"):
        if not isinstance(r, CategoryRule) or r.archived:
            continue
        if r.category_id in archived_ids:
            rule_writes.append(
                r.model_copy(update={"is_active": False, "updated_at": now})
            )
            rules_off += 1
    to_write.append(cat.model_copy(update={"archived": True, "updated_at": now}))
    if to_write:
        repo.upsert_rows("Categories", to_write)
    if tx_writes:
        repo.upsert_rows("Transactions", tx_writes)
    if rule_writes:
        repo.upsert_rows("CategoryRules", rule_writes)
    cache_invalidate()
    return {
        "archived_ids": [str(i) for i in archived_ids],
        "transactions_touched": reassigned,
        "rules_deactivated": rules_off,
    }


# Narrative patterns for Revolut vault / spare-change / own multi-ccy FX
_REVOLUT_SAVINGS_INTERNAL_NEEDLES = (
    "exchanged to",
    "exchange to",
    "pocket withdrawal",
    "to pocket",
    "purchase vault",
    "from vault",
    "vault to",
)


def is_revolut_savings_or_own_fx_narrative(tx: Transaction) -> bool:
    blob = " ".join(
        filter(
            None,
            [
                tx.merchant,
                tx.description,
                tx.original_description,
                tx.notes,
            ],
        )
    ).lower()
    return any(n in blob for n in _REVOLUT_SAVINGS_INTERNAL_NEEDLES)


def repair_revolut_savings_transfers(
    repo: SheetsRepository,
    *,
    skip_user_overrides: bool = True,
) -> dict[str, Any]:
    """
    Reclassify spare-change / vault / own FX rows as Internal transfer and set
    ``is_internal_transfer=True`` so they drop out of spend/income.

    Also rewires active CategoryRules that still map those needles to External
    transfer or Cash withdrawal.
    """
    now = utc_now()
    ensure_default_categories(repo)

    # --- Fix rules ---
    rules = [
        r for r in repo.list_rows("CategoryRules") if isinstance(r, CategoryRule) and not r.archived
    ]
    rules_to_write: list[CategoryRule] = []
    for r in rules:
        needle = (r.match_value or "").lower()
        is_savings_needle = any(n in needle for n in _REVOLUT_SAVINGS_INTERNAL_NEEDLES)
        if not is_savings_needle:
            continue
        needs = (
            r.category_id != CAT_INTERNAL
            or not r.set_internal_transfer
            or not r.is_active
        )
        if needs:
            rules_to_write.append(
                r.model_copy(
                    update={
                        "category_id": CAT_INTERNAL,
                        "set_internal_transfer": True,
                        "is_active": True,
                        "notes": ((r.notes or "") + "; repair:savings_internal").strip("; "),
                        "updated_at": now,
                    }
                )
            )
    rules_updated = len(rules_to_write)
    if rules_to_write:
        repo.upsert_rows("CategoryRules", rules_to_write)

    # --- Fix transactions ---
    txs = [t for t in repo.list_rows("Transactions") if isinstance(t, Transaction)]
    updated_txs: list[Transaction] = []
    skipped_override = 0
    already_ok = 0
    for t in txs:
        if t.archived:
            continue
        if not is_revolut_savings_or_own_fx_narrative(t):
            continue
        if skip_user_overrides and t.category_override:
            skipped_override += 1
            continue
        if t.category_id == CAT_INTERNAL and t.is_internal_transfer:
            already_ok += 1
            continue
        updated_txs.append(
            t.model_copy(
                update={
                    "category_id": CAT_INTERNAL,
                    "is_internal_transfer": True,
                    "updated_at": now,
                }
            )
        )

    if updated_txs:
        repo.upsert_rows("Transactions", updated_txs)

    return {
        "transactions_updated": len(updated_txs),
        "transactions_already_ok": already_ok,
        "transactions_skipped_override": skipped_override,
        "rules_updated": rules_updated,
    }


# ---------------------------------------------------------------------------
# Raiffeisen ↔ Revolut own-account pot moves
# ---------------------------------------------------------------------------

# Bill / merchant exclusions so own-account detector does not swallow real spend
_OWN_ACCOUNT_EXCLUDE = (
    "allianz",
    "vodafone",
    "energetika",
    "plynárensk",
    "plynarensk",
    "insurance",
    " rent",
    "najem",
    "nájem",
)

# Rules that wrongly map self-wires to External — rewire to Internal
# (institution-generic only; no personal-name needles)
_OWN_ACCOUNT_RULE_REWIRE = (
    "sent from revolut",
    "revolut**",
    "card payment — revolut",
    "single payment — revolut",
    "revolut transfer",
    "transfer to my",
    "between own accounts",
    "to main account",
)


def _tx_narrative_blob(tx: Transaction) -> str:
    return " ".join(
        filter(
            None,
            [
                tx.merchant,
                tx.description,
                tx.original_description,
                tx.counterparty_name,
                tx.notes,
            ],
        )
    ).lower()


def is_own_account_bank_transfer(tx: Transaction) -> bool:
    """
    True for high-confidence Raiffeisen ↔ Revolut pot moves (not bills / partner).
    """
    blob = _tx_narrative_blob(tx)
    if any(x in blob for x in _OWN_ACCOUNT_EXCLUDE):
        return False

    desc = (tx.description or "").lower()
    orig = (tx.original_description or "").lower()
    merch = (tx.merchant or "").strip().lower()
    inst = (tx.source_institution or "").strip().lower()

    # Raiffeisen ← Revolut bank transfer (institution-generic narratives)
    if "sent from revolut" in orig or "sent from revolut" in desc:
        return True
    if "single payment" in desc and "revolut" in desc and "card payment" not in desc:
        return True
    if "revolut transfer" in desc:
        return True
    if "transfer to my" in orig:
        return True
    if "between own accounts" in desc or "to main account" in desc:
        return True

    # Raiffeisen card top-up funding Revolut (Card payment — Revolut**…)
    if inst == "raiffeisen":
        is_cardish = (
            "card payment" in desc
            or "apple pay" in desc
            or "google pay" in desc
        )
        is_rev_card = (
            "revolut**" in desc
            or "revolut**" in orig
            or merch == "revolut"
        )
        if is_cardish and is_rev_card:
            return True

    return False


def repair_own_account_bank_transfers(
    repo: SheetsRepository,
    *,
    skip_user_overrides: bool = True,
) -> dict[str, Any]:
    """
    Reclassify RB↔Revolut pot moves (wires + card top-ups) as Internal transfer.
    """
    now = utc_now()
    ensure_default_categories(repo)

    rules = [
        r for r in repo.list_rows("CategoryRules") if isinstance(r, CategoryRule) and not r.archived
    ]
    rules_to_write: list[CategoryRule] = []
    for r in rules:
        needle = (r.match_value or "").lower()
        if not any(n in needle for n in _OWN_ACCOUNT_RULE_REWIRE):
            continue
        needs = (
            r.category_id != CAT_INTERNAL
            or not r.set_internal_transfer
            or not r.is_active
        )
        if needs:
            rules_to_write.append(
                r.model_copy(
                    update={
                        "category_id": CAT_INTERNAL,
                        "set_internal_transfer": True,
                        "is_active": True,
                        "notes": ((r.notes or "") + "; repair:own_account_internal").strip("; "),
                        "updated_at": now,
                    }
                )
            )
    rules_updated = len(rules_to_write)
    if rules_to_write:
        repo.upsert_rows("CategoryRules", rules_to_write)

    updated_txs: list[Transaction] = []
    skipped_override = 0
    already_ok = 0
    matched = 0
    for t in repo.list_rows("Transactions"):
        if not isinstance(t, Transaction) or t.archived:
            continue
        if not is_own_account_bank_transfer(t):
            continue
        matched += 1
        if skip_user_overrides and t.category_override:
            skipped_override += 1
            continue
        if t.category_id == CAT_INTERNAL and t.is_internal_transfer:
            already_ok += 1
            continue
        updated_txs.append(
            t.model_copy(
                update={
                    "category_id": CAT_INTERNAL,
                    "is_internal_transfer": True,
                    "updated_at": now,
                }
            )
        )

    if updated_txs:
        repo.upsert_rows("Transactions", updated_txs)
        cache_invalidate()

    return {
        "matched": matched,
        "transactions_updated": len(updated_txs),
        "transactions_already_ok": already_ok,
        "transactions_skipped_override": skipped_override,
        "rules_updated": rules_updated,
    }


# ---------------------------------------------------------------------------
# Revolut Digital Assets Europe (crypto pot funding / sell proceeds)
# ---------------------------------------------------------------------------

_DIGITAL_ASSETS_NEEDLE = "revolut digital assets europe"
_DIGITAL_ASSETS_RULE_VALUE = "Revolut Digital Assets Europe Ltd"


def is_revolut_digital_assets_transfer(tx: Transaction) -> bool:
    """
    True for cash legs between Revolut Current and Digital Assets Europe.

    These fund crypto buys / return sell proceeds; InvestmentEvents already
    hold the real trade economics from the crypto statement.
    """
    return _DIGITAL_ASSETS_NEEDLE in _tx_narrative_blob(tx)


def repair_revolut_digital_assets_transfers(
    repo: SheetsRepository,
    *,
    skip_user_overrides: bool = True,
) -> dict[str, Any]:
    """
    Reclassify Digital Assets Europe pot moves as Crypto funding + internal.

    Ensures a high-priority CategoryRule so future imports auto-flag, and
    rewrites existing matching transactions (skips user overrides by default).
    """
    now = utc_now()
    ensure_default_categories(repo)

    rules = [
        r for r in repo.list_rows("CategoryRules") if isinstance(r, CategoryRule) and not r.archived
    ]
    rules_to_write: list[CategoryRule] = []
    found_rule = False
    for r in rules:
        needle = (r.match_value or "").lower()
        if _DIGITAL_ASSETS_NEEDLE not in needle:
            continue
        found_rule = True
        needs = (
            r.category_id != CAT_CRYPTO_FUND
            or not r.set_internal_transfer
            or not r.is_active
            or r.priority > 10
        )
        if needs:
            rules_to_write.append(
                r.model_copy(
                    update={
                        "category_id": CAT_CRYPTO_FUND,
                        "set_internal_transfer": True,
                        "is_active": True,
                        "priority": min(r.priority, 6),
                        "notes": (
                            (r.notes or "") + "; repair:digital_assets_crypto_pot"
                        ).strip("; "),
                        "updated_at": now,
                    }
                )
            )

    if not found_rule:
        rules_to_write.append(
            CategoryRule(
                id=uuid4(),
                priority=6,
                match_field=MatchField.DESCRIPTION,
                match_type=MatchType.CONTAINS,
                match_value=_DIGITAL_ASSETS_RULE_VALUE,
                category_id=CAT_CRYPTO_FUND,
                set_internal_transfer=True,
                institution_scope=None,
                is_active=True,
                notes="repair:digital_assets_crypto_pot",
                created_at=now,
                updated_at=now,
            )
        )

    rules_updated = len(rules_to_write)
    if rules_to_write:
        repo.upsert_rows("CategoryRules", rules_to_write)

    updated_txs: list[Transaction] = []
    skipped_override = 0
    already_ok = 0
    matched = 0
    for t in repo.list_rows("Transactions"):
        if not isinstance(t, Transaction) or t.archived:
            continue
        if not is_revolut_digital_assets_transfer(t):
            continue
        matched += 1
        if skip_user_overrides and t.category_override:
            skipped_override += 1
            continue
        if t.category_id == CAT_CRYPTO_FUND and t.is_internal_transfer:
            already_ok += 1
            continue
        updated_txs.append(
            t.model_copy(
                update={
                    "category_id": CAT_CRYPTO_FUND,
                    "is_internal_transfer": True,
                    "updated_at": now,
                }
            )
        )

    if updated_txs:
        repo.upsert_rows("Transactions", updated_txs)
        cache_invalidate()

    return {
        "matched": matched,
        "transactions_updated": len(updated_txs),
        "transactions_already_ok": already_ok,
        "transactions_skipped_override": skipped_override,
        "rules_updated": rules_updated,
    }
