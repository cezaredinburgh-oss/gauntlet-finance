/**
 * Self-test for ruleExplain helpers.
 * Run: npx --yes tsx src/lib/ruleExplain.selftest.ts  (from frontend/)
 */
import {
  analyseRuleAgainstEvidence,
  describeRuleMatch,
  refineMatchValueFromEvidence,
} from "./ruleExplain";
import type { Transaction } from "../api/types";

function makeTx(
  partial: Partial<Transaction> & { id: string },
): Transaction {
  return {
    booking_date: "2026-01-01",
    amount: "-100",
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

const s = describeRuleMatch({
  match_field: "merchant",
  match_type: "contains",
  match_value: "Lidl",
  institution_scope: null,
});
if (!s.includes("merchant contains") || !s.includes("Lidl")) {
  throw new Error("describeRuleMatch failed");
}

const analysis = analyseRuleAgainstEvidence(
  {
    match_field: "merchant",
    match_type: "contains",
    match_value: "vodafone",
    institution_scope: null,
  },
  "Utilities",
  [makeTx({ id: "1", merchant: "Vodafone CZ" })],
  [makeTx({ id: "2", merchant: "Vodafone Shop Praha" })],
);
if (!analysis.warning || analysis.excludedStillMatched.length !== 1) {
  throw new Error("exclusion warning failed");
}

// Single included label whose contains-match still hits an exclusion → prefer exact
const refined = refineMatchValueFromEvidence(
  {
    match_field: "merchant",
    match_type: "contains",
    match_value: "Vodafone",
    institution_scope: null,
    candidates: [],
  },
  [makeTx({ id: "1", merchant: "Vodafone" })],
  [makeTx({ id: "2", merchant: "Vodafone Shop" })],
);
if (refined.match_type !== "exact" || refined.match_value !== "Vodafone") {
  throw new Error(
    `expected exact Vodafone, got ${refined.match_type} ${refined.match_value}`,
  );
}

console.log("ruleExplain.selftest: ok");
