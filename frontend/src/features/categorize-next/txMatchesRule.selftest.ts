/**
 * Matcher parity with backend/engines/categorize.py::rule_matches.
 * Run: npx --yes tsx src/features/categorize-next/txMatchesRule.selftest.ts  (from frontend/)
 */
import type { Transaction } from "../../api/types";
import {
  transactionsMatchingRule,
  txMatchesRule,
  type RuleMatchSpec,
} from "../../lib/ruleSuggest";

function assertEq(actual: unknown, expected: unknown, msg: string): void {
  if (actual !== expected) {
    throw new Error(`${msg}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

function tx(partial: Partial<Transaction> = {}): Transaction {
  return {
    id: partial.id ?? "t1",
    account_id: "a1",
    booking_date: "2026-06-04",
    amount: partial.amount ?? "-10",
    currency: "CZK",
    fee_amount: "0",
    merchant: partial.merchant ?? null,
    description: partial.description ?? null,
    original_description: partial.original_description ?? null,
    counterparty_name: partial.counterparty_name ?? null,
    source_institution: partial.source_institution ?? "Raiffeisen",
    category_id: partial.category_id ?? null,
    category_override: partial.category_override ?? false,
    is_internal_transfer: partial.is_internal_transfer ?? false,
  };
}

function rule(partial: Partial<RuleMatchSpec> = {}): RuleMatchSpec {
  return {
    match_field: "merchant",
    match_type: "contains",
    match_value: "shop",
    is_active: true,
    ...partial,
  };
}

// exact_case: course payment, not title-case / substring (engine test_self_education)
const exactCase = rule({
  match_field: "original_description",
  match_type: "exact_case",
  match_value: "CEZARY BIERNAT",
});
assertEq(
  txMatchesRule(tx({ original_description: "CEZARY BIERNAT" }), exactCase),
  true,
  "exact_case matches identical casing",
);
assertEq(
  txMatchesRule(tx({ original_description: "Cezary Biernat" }), exactCase),
  false,
  "exact_case rejects title case",
);
assertEq(
  txMatchesRule(tx({ original_description: "Tax 2025, Cezary Biernat" }), exactCase),
  false,
  "exact_case rejects substring",
);

// exact is case-insensitive
const exact = rule({ match_field: "merchant", match_type: "exact", match_value: "Shop" });
assertEq(txMatchesRule(tx({ merchant: "SHOP" }), exact), true, "exact ignores case");
assertEq(txMatchesRule(tx({ merchant: "Shoppe" }), exact), false, "exact is whole field");

// contains is case-insensitive
const contains = rule({ match_field: "description", match_type: "contains", match_value: "Vault" });
assertEq(
  txMatchesRule(tx({ description: "to VAULT savings" }), contains),
  true,
  "contains ignores case",
);

// starts_with
const starts = rule({
  match_field: "description",
  match_type: "starts_with",
  match_value: "outgoing",
});
assertEq(
  txMatchesRule(tx({ description: "Outgoing instant payment" }), starts),
  true,
  "starts_with ignores case",
);
assertEq(
  txMatchesRule(tx({ description: "Card outgoing" }), starts),
  false,
  "starts_with is prefix only",
);

// counterparty_name field
const cp = rule({
  match_field: "counterparty_name",
  match_type: "contains",
  match_value: "biernat",
});
assertEq(
  txMatchesRule(tx({ counterparty_name: "Cezary Biernat", merchant: "Other" }), cp),
  true,
  "counterparty_name is a match field",
);
assertEq(
  txMatchesRule(tx({ counterparty_name: "Acme", merchant: "Biernat shop" }), cp),
  false,
  "counterparty_name does not fall back to merchant",
);

// regex IGNORECASE; invalid regex = no match
const regexOk = rule({ match_field: "merchant", match_type: "regex", match_value: "cof+ee" });
assertEq(txMatchesRule(tx({ merchant: "COFFEE" }), regexOk), true, "regex IGNORECASE");
const regexBad = rule({ match_field: "merchant", match_type: "regex", match_value: "[unclosed" });
assertEq(txMatchesRule(tx({ merchant: "coffee" }), regexBad), false, "invalid regex = no match");

// institution_scope case-insensitive vs source_institution
const scoped = rule({
  match_field: "merchant",
  match_type: "contains",
  match_value: "shop",
  institution_scope: "Revolut",
});
assertEq(
  txMatchesRule(tx({ merchant: "shop", source_institution: "revolut" }), scoped),
  true,
  "institution_scope ignores case",
);
assertEq(
  txMatchesRule(tx({ merchant: "shop", source_institution: "Raiffeisen" }), scoped),
  false,
  "institution_scope mismatch = no match",
);

// inactive / archived
assertEq(
  txMatchesRule(tx({ merchant: "shop" }), rule({ is_active: false })),
  false,
  "inactive rule matches nothing",
);
assertEq(
  txMatchesRule(tx({ merchant: "shop" }), rule({ archived: true })),
  false,
  "archived rule matches nothing",
);

const internals = [
  tx({ id: "i1", merchant: "DAE", is_internal_transfer: true }),
  tx({ id: "e1", merchant: "DAE", is_internal_transfer: false }),
  tx({ id: "x1", merchant: "other" }),
];
const matched = transactionsMatchingRule(
  internals,
  rule({ match_field: "merchant", match_type: "exact", match_value: "dae" }),
);
assertEq(matched.map((t) => t.id).join(","), "i1,e1", "preview includes internals and categorized");

console.log("txMatchesRule.selftest: ok");
