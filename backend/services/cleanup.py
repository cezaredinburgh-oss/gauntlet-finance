"""
Scoped cleanup of Google Sheets / in-memory ledger data.

Destructive helpers used by the admin API and CLI. Never touch files outside
the app repository (Bank statements / Sheets only via the repository).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.schema.models import SHEET_HEADERS, Transaction
from backend.sheets.repository import SheetsRepository

CONFIRM_TOKEN = "DELETE"

# Atomic tab groups expanded from user-facing scope ids
_SCOPE_TABS: dict[str, tuple[str, ...]] = {
    "transactions": ("Transactions",),
    "investments": ("InvestmentEvents", "InvestmentLots"),
    "categories": ("Categories", "CategoryRules"),
    "statement_files": ("StatementFiles",),
    "prices": ("Prices",),
    "fx_rates": ("FXRates",),
    "accounts": ("Accounts",),
}

_COMPOSITE: dict[str, tuple[str, ...]] = {
    "all_ledger": ("transactions", "investments", "statement_files"),
    "everything_except_settings": (
        "transactions",
        "investments",
        "categories",
        "statement_files",
        "prices",
        "fx_rates",
        "accounts",
    ),
}

SCOPE_META: dict[str, dict[str, str]] = {
    "transactions": {
        "label": "Checking / cash transactions",
        "description": "Clears the Transactions tab (bank cash ledger).",
    },
    "investments": {
        "label": "Investments",
        "description": "Clears InvestmentEvents and InvestmentLots (broker history + open lots).",
    },
    "categories": {
        "label": "Categories & rules",
        "description": (
            "Deletes Categories and CategoryRules only. Unassigns categories on "
            "existing cash transactions (does not delete uploaded statement data, "
            "transactions, investments, or StatementFiles)."
        ),
    },
    "statement_files": {
        "label": "Statement file registry",
        "description": "Clears StatementFiles so the same file can be re-uploaded (SHA-256 gate). Does not delete txs/lots.",
    },
    "prices": {
        "label": "Prices",
        "description": "Clears cached market prices.",
    },
    "fx_rates": {
        "label": "FX rates",
        "description": "Clears stored FX rates (e.g. CNB).",
    },
    "accounts": {
        "label": "Accounts",
        "description": "Clears Accounts. Warning: leave txs/lots in place only if you re-seed accounts first.",
    },
    "all_ledger": {
        "label": "All money history",
        "description": "Transactions + investments + statement registry. Keeps categories, accounts, prices, settings.",
    },
    "everything_except_settings": {
        "label": "Everything except Settings",
        "description": "Factory reset of ledger, categories, accounts, prices, and FX. Keeps Settings tab only.",
    },
}


def list_scopes() -> list[dict[str, str]]:
    """Stable order for UI."""
    order = [
        "transactions",
        "investments",
        "categories",
        "statement_files",
        "prices",
        "fx_rates",
        "accounts",
        "all_ledger",
        "everything_except_settings",
    ]
    out = []
    for sid in order:
        meta = SCOPE_META[sid]
        out.append({"id": sid, "label": meta["label"], "description": meta["description"]})
    return out


def expand_scopes(scopes: list[str]) -> list[str]:
    """Expand composites; return unique atomic scope ids in deterministic order."""
    atomic: list[str] = []
    seen: set[str] = set()
    for raw in scopes:
        s = (raw or "").strip().lower()
        if not s:
            continue
        if s in _COMPOSITE:
            for child in _COMPOSITE[s]:
                if child not in seen:
                    seen.add(child)
                    atomic.append(child)
        elif s in _SCOPE_TABS:
            if s not in seen:
                seen.add(s)
                atomic.append(s)
        else:
            raise ValueError(f"unknown cleanup scope: {raw!r}")
    return atomic


def _count_tab(repo: SheetsRepository, tab: str) -> int:
    return len(repo.list_rows(tab))


def preview_cleanup(repo: SheetsRepository) -> dict[str, Any]:
    """Row counts per scope for the Settings UI."""
    tab_counts = {tab: _count_tab(repo, tab) for tab in SHEET_HEADERS}
    scopes_out = []
    for meta in list_scopes():
        sid = meta["id"]
        atomics = expand_scopes([sid])
        tabs: list[str] = []
        for a in atomics:
            tabs.extend(_SCOPE_TABS[a])
        # unique preserve order
        seen_t: set[str] = set()
        tabs_u = []
        for t in tabs:
            if t not in seen_t:
                seen_t.add(t)
                tabs_u.append(t)
        row_counts = {t: tab_counts.get(t, 0) for t in tabs_u}
        notes = ""
        if sid == "categories":
            notes = (
                "Safe for ledger history: keeps Transactions, StatementFiles, and "
                "investments. Only drops category trees/rules and nulls category_id "
                "on cash txs (patch — never full-tab wipe)."
            )
        if sid == "statement_files":
            notes = "Re-import still dedupes txs/events unless those scopes are cleared too."
        if sid == "accounts":
            notes = "Dangerous if transactions or lots still reference account ids."
        scopes_out.append(
            {
                **meta,
                "tabs": tabs_u,
                "row_counts": row_counts,
                "total_rows": sum(row_counts.values()),
                "notes": notes,
            }
        )
    return {
        "scopes": scopes_out,
        "tab_counts": tab_counts,
        "confirm_token": CONFIRM_TOKEN,
    }


@dataclass
class CleanupResult:
    scopes_requested: list[str]
    scopes_applied: list[str]
    tabs_cleared: dict[str, int] = field(default_factory=dict)
    transactions_uncategorized: int = 0
    message: str = "ok"


def _clear_tab(repo: SheetsRepository, tab: str) -> int:
    before = _count_tab(repo, tab)
    repo.replace_all_rows(tab, [])
    return before


def _clear_transaction_categories(repo: SheetsRepository) -> int:
    """
    Null category assignments on cash transactions.

    Uses upsert/patch only — never ``replace_all_rows`` on Transactions.
    Full-tab replace is clear+rewrite on Google Sheets and can wipe the ledger
    if the write fails mid-flight or if a partial cache were ever rewritten.
    """
    rows = [r for r in repo.list_rows("Transactions") if isinstance(r, Transaction)]
    updated: list[Transaction] = []
    for t in rows:
        if t.category_id is not None or t.category_override:
            updated.append(
                t.model_copy(update={"category_id": None, "category_override": False})
            )
    if updated:
        repo.upsert_rows("Transactions", updated)
    return len(updated)


# Tabs that categories-only cleanup must never clear entirely.
_CATEGORIES_FORBIDDEN_TABS = frozenset(
    {
        "Transactions",
        "StatementFiles",
        "InvestmentLots",
        "InvestmentEvents",
        "Accounts",
        "Prices",
        "FXRates",
        "Settings",
        "PortfolioSnapshots",
    }
)


def run_cleanup(repo: SheetsRepository, scopes: list[str]) -> CleanupResult:
    """
    Execute cleanup for the given scope ids (atomic or composite).

    Idempotent: clearing an already-empty tab is fine.

    ``categories`` only deletes Categories/CategoryRules and unassigns
    category_id on cash txs — never deletes statement history tabs.
    """
    requested = list(scopes)
    applied = expand_scopes(scopes)
    if not applied:
        raise ValueError("no scopes selected")

    tabs_cleared: dict[str, int] = {}
    uncategorized = 0

    # Deterministic order: data first, accounts last if present
    order = [
        "transactions",
        "investments",
        "categories",
        "statement_files",
        "prices",
        "fx_rates",
        "accounts",
    ]
    ordered = [s for s in order if s in applied]

    # Snapshot counts for ledger tabs so categories-only cannot silently shrink them
    ledger_before: dict[str, int] = {}
    if "categories" in ordered and "transactions" not in ordered:
        for tab in (
            "Transactions",
            "StatementFiles",
            "InvestmentLots",
            "InvestmentEvents",
        ):
            try:
                ledger_before[tab] = _count_tab(repo, tab)
            except Exception:  # noqa: BLE001
                ledger_before[tab] = -1

    for scope in ordered:
        if scope == "categories":
            for tab in _SCOPE_TABS["categories"]:
                if tab in _CATEGORIES_FORBIDDEN_TABS:
                    raise RuntimeError(
                        f"internal error: categories scope tried to clear {tab}"
                    )
                tabs_cleared[tab] = tabs_cleared.get(tab, 0) + _clear_tab(repo, tab)
            uncategorized += _clear_transaction_categories(repo)
            continue
        for tab in _SCOPE_TABS[scope]:
            tabs_cleared[tab] = tabs_cleared.get(tab, 0) + _clear_tab(repo, tab)

    if ledger_before:
        for tab, before in ledger_before.items():
            if before < 0:
                continue
            after = _count_tab(repo, tab)
            if after < before:
                raise RuntimeError(
                    f"categories cleanup must not remove {tab} rows "
                    f"(before={before}, after={after})"
                )

    return CleanupResult(
        scopes_requested=requested,
        scopes_applied=ordered,
        tabs_cleared=tabs_cleared,
        transactions_uncategorized=uncategorized,
        message="ok",
    )


def result_to_dict(result: CleanupResult) -> dict[str, Any]:
    return {
        "scopes_requested": result.scopes_requested,
        "scopes_applied": result.scopes_applied,
        "tabs_cleared": result.tabs_cleared,
        "transactions_uncategorized": result.transactions_uncategorized,
        "message": result.message,
    }
