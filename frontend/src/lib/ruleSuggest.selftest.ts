/**
 * Self-test for vendor rollup grouping.
 * Run: npx --yes tsx src/lib/ruleSuggest.selftest.ts  (from frontend/)
 */
import {
  applyVendorCategoryOverrides,
  CATCHALL_CATEGORY_IDS,
  formatVendorPreview,
  groupTransactionsByVendor,
  groupVendorsByCategory,
  isResidualCategory,
  ledgerCategoryCounts,
} from "./ruleSuggest";
import type { Category, Transaction } from "../api/types";

function tx(
  partial: Partial<Transaction> & { id: string },
): Transaction {
  return {
    booking_date: "2026-01-01",
    amount: "-10",
    currency: "USD",
    source_institution: "Revolut",
    category_override: false,
    is_internal_transfer: false,
    merchant: null,
    description: null,
    original_description: null,
    ...partial,
  } as Transaction;
}

const rows: Transaction[] = [
  ...Array.from({ length: 18 }, (_, i) =>
    tx({ id: `mcd-${i}`, merchant: "McDonalds", amount: "-8" }),
  ),
  tx({ id: "lidl-1", merchant: "Lidl", amount: "-12" }),
  tx({ id: "lidl-2", merchant: "Lidl", amount: "-15" }),
  tx({ id: "one", merchant: "Unique Cafe", amount: "-4" }),
];

const grouped = groupTransactionsByVendor(rows);
if (grouped.length !== 3) throw new Error(`expected 3 vendors, got ${grouped.length}`);
if (grouped[0].label !== "McDonalds" || grouped[0].count !== 18) {
  throw new Error(`expected McDonalds x18 first, got ${grouped[0].label} x${grouped[0].count}`);
}
if (grouped[1].label !== "Lidl" || grouped[1].count !== 2) {
  throw new Error(`expected Lidl x2 second, got ${grouped[1].label} x${grouped[1].count}`);
}
if (grouped[2].ids.length !== 1 || grouped[2].ids[0] !== "one") {
  throw new Error("unique vendor should keep its id");
}

const empty = groupTransactionsByVendor([]);
if (empty.length !== 0) throw new Error("empty input should be empty");

const groceries = {
  id: "cat-groc",
  name: "Groceries",
  necessity: "variable",
  life_domain: "Food",
  is_income: false,
  is_transfer: false,
  sort_order: 1,
} as Category;
const catMap = new Map<string, Category>([[groceries.id, groceries]]);
const counted = ledgerCategoryCounts(
  [
    tx({ id: "a", merchant: "Lidl", category_id: groceries.id }),
    tx({ id: "b", merchant: "Lidl" }),
    tx({ id: "c", merchant: "Lidl" }),
    tx({
      id: "d",
      merchant: "Revolut",
      is_internal_transfer: true,
      category_id: groceries.id,
    }),
  ],
  catMap,
);
if (counted.categorized !== 1 || counted.uncategorized !== 2 || counted.total !== 3) {
  throw new Error(
    `expected 1/2 of 3, got ${counted.categorized}/${counted.uncategorized} of ${counted.total}`,
  );
}
const afterAssign = ledgerCategoryCounts(
  [
    tx({ id: "a", merchant: "Lidl", category_id: groceries.id }),
    tx({ id: "b", merchant: "Lidl", category_id: groceries.id }),
    tx({ id: "c", merchant: "Lidl", category_id: groceries.id }),
  ],
  catMap,
);
if (afterAssign.uncategorized !== 0 || afterAssign.categorized !== 3) {
  throw new Error("assigning a group should zero the uncategorized count");
}

const travel = {
  id: "travel-cfec61",
  name: "Travel",
  necessity: "discretionary",
  life_domain: "Other",
  is_income: false,
  is_transfer: false,
  sort_order: 2,
} as Category;
const catchAllOther = {
  ...groceries,
  id: "c2000001-0000-4000-8000-000000000140",
  name: "Other",
  life_domain: "Other",
} as Category;
if (!CATCHALL_CATEGORY_IDS.has(catchAllOther.id)) {
  throw new Error("CAT_OTHER UUID must be in CATCHALL_CATEGORY_IDS");
}
const residualMap = new Map<string, Category>([
  [travel.id, travel],
  [catchAllOther.id, catchAllOther],
]);
const travelTx = tx({ id: "hotel-1", merchant: "Hotel", category_id: travel.id });
const otherTx = tx({ id: "misc-1", merchant: "Misc", category_id: catchAllOther.id });
if (isResidualCategory(travelTx, residualMap)) {
  throw new Error("Travel with life_domain Other must not be residual");
}
if (!isResidualCategory(otherTx, residualMap)) {
  throw new Error("CAT_OTHER UUID spend must stay residual");
}
const travelCounts = ledgerCategoryCounts(
  [travelTx, otherTx, tx({ id: "blank-1", merchant: "Blank" })],
  residualMap,
);
if (
  travelCounts.categorized !== 1 ||
  travelCounts.uncategorized !== 2 ||
  travelCounts.total !== 3
) {
  throw new Error(
    `expected Travel categorized 1/2 of 3, got ${travelCounts.categorized}/${travelCounts.uncategorized} of ${travelCounts.total}`,
  );
}

const byCat = groupVendorsByCategory([
  {
    key: "m:rohlik",
    label: "Rohlik.cz",
    count: 10,
    ids: ["1"],
    suggestedCategoryId: "groc",
    suggestedCategoryName: "Groceries",
  },
  {
    key: "m:lidl",
    label: "Lidl",
    count: 5,
    ids: ["2"],
    suggestedCategoryId: "groc",
    suggestedCategoryName: "Groceries",
  },
  {
    key: "m:uber",
    label: "Uber",
    count: 3,
    ids: ["3"],
    suggestedCategoryId: "taxi",
    suggestedCategoryName: "Taxi / rideshare",
  },
  { key: "m:mystery", label: "???", count: 1, ids: ["4"] },
]);
if (byCat.groups.length !== 2) throw new Error("expected 2 category groups");
if (byCat.groups[0].categoryName !== "Groceries" || byCat.groups[0].txCount !== 15) {
  throw new Error("Groceries should rank first by tx count");
}
if (byCat.unassigned.length !== 1 || byCat.unassigned[0].label !== "???") {
  throw new Error("unassigned should keep unmatched vendors");
}
const remapped = applyVendorCategoryOverrides(
  [
    {
      key: "m:mol",
      label: "MOL",
      count: 4,
      ids: ["m1"],
      suggestedCategoryId: "fuel",
      suggestedCategoryName: "Fuel (car)",
    },
  ],
  { "m:mol": "moto" },
  [
    { ...groceries, id: "fuel", name: "Fuel (car)" },
    { ...groceries, id: "moto", name: "Moto fuel" },
  ],
);
const remappedGroups = groupVendorsByCategory(remapped);
if (remappedGroups.groups.length !== 1 || remappedGroups.groups[0].categoryName !== "Moto fuel") {
  throw new Error("remapping a vendor should move it to the new category group");
}

if (formatVendorPreview(["Rohlik", "Lidl"], 80) !== "Rohlik, Lidl") {
  throw new Error("short preview should list all names");
}
if (!formatVendorPreview(["Aaaaaaaa", "Bbbbbbbb", "Cccccccc"], 20).includes("+")) {
  throw new Error("long preview should add +N more");
}

console.log("ruleSuggest.selftest: ok");
