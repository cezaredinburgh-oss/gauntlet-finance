"""
Deterministic vendor → leaf-category pass used by Ask Grok+.

Delegates to the universal core pack. Never writes the ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.engines.core_pack import match_core_pack, unwrap_vendor_label
from backend.schema.default_categories import DEFAULT_CATEGORIES
from backend.schema.models import Category

if TYPE_CHECKING:
    from backend.services.ai_categorize import MerchantCluster

__all__ = [
    "LocalGuess",
    "PreclassifyResult",
    "preclassify_clusters",
    "unwrap_vendor_label",
]


@dataclass(frozen=True)
class LocalGuess:
    cluster: MerchantCluster
    category_id: str
    category_name: str
    reason: str


@dataclass(frozen=True)
class PreclassifyResult:
    resolved: list[LocalGuess]
    leftovers: list[MerchantCluster]


def _as_categories(catalog: list[Any]) -> list[Category]:
    if not catalog:
        return list(DEFAULT_CATEGORIES)
    if isinstance(catalog[0], Category):
        return [c for c in catalog if isinstance(c, Category)]
    by_id = {str(c.id): c for c in DEFAULT_CATEGORIES}
    by_name = {c.name.lower(): c for c in DEFAULT_CATEGORIES}
    out: list[Category] = []
    seen: set[str] = set()
    for row in catalog:
        if not isinstance(row, dict):
            continue
        found = by_id.get(str(row.get("id") or "")) or by_name.get(
            (row.get("name") or "").strip().lower()
        )
        if found and str(found.id) not in seen:
            seen.add(str(found.id))
            out.append(found)
    return out or list(DEFAULT_CATEGORIES)


def preclassify_clusters(
    clusters: list[MerchantCluster],
    catalog: list[Any],
) -> PreclassifyResult:
    cats = _as_categories(catalog)
    resolved: list[LocalGuess] = []
    leftovers: list[MerchantCluster] = []
    for cluster in clusters:
        hit = match_core_pack(
            cluster.label,
            cluster.description_sample or "",
            cats,
        )
        if hit is None:
            leftovers.append(cluster)
        else:
            resolved.append(
                LocalGuess(
                    cluster=cluster,
                    category_id=str(hit.category_id),
                    category_name=hit.category_name,
                    reason=hit.reason,
                )
            )
    return PreclassifyResult(resolved=resolved, leftovers=leftovers)
