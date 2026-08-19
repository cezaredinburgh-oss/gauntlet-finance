/**
 * Plain-English category rule previews and exclusion-aware warnings.
 */

import type { Transaction } from "../api/types";
import { txMatchesRule, type RuleSuggestion } from "./ruleSuggest";

export { txMatchesRule };

export function describeRuleMatch(opts: {
  match_field: string;
  match_type: string;
  match_value: string;
  institution_scope?: string | null;
}): string {
  const field = opts.match_field.replace(/_/g, " ");
  const value = opts.match_value.trim() || "…";
  let when: string;
  switch (opts.match_type) {
    case "exact":
    case "exact_case":
      when = `${field} is exactly “${value}”`;
      break;
    case "starts_with":
      when = `${field} starts with “${value}”`;
      break;
    case "regex":
      when = `${field} matches pattern /${value}/`;
      break;
    default:
      when = `${field} contains “${value}”`;
  }
  if (opts.institution_scope?.trim()) {
    when += ` (only at ${opts.institution_scope.trim()})`;
  } else {
    when += " (any bank)";
  }
  return when;
}

export function describeRuleAction(categoryName: string): string {
  return `set category to ${categoryName}`;
}

export type RuleExclusionAnalysis = {
  includedMatched: number;
  includedTotal: number;
  excludedStillMatched: Transaction[];
  warning: string | null;
  plainEnglish: string;
};

/**
 * Analyse a proposed rule against included (accepted) and excluded (rejected) txs.
 */
export function analyseRuleAgainstEvidence(
  rule: Pick<
    RuleSuggestion,
    "match_field" | "match_type" | "match_value" | "institution_scope"
  >,
  categoryName: string,
  included: Transaction[],
  excluded: Transaction[],
): RuleExclusionAnalysis {
  const when = describeRuleMatch({
    match_field: rule.match_field,
    match_type: rule.match_type,
    match_value: rule.match_value,
    institution_scope: rule.institution_scope,
  });
  const plainEnglish = `When ${when}, ${describeRuleAction(categoryName)}.`;

  let includedMatched = 0;
  for (const t of included) {
    if (
      txMatchesRule(t, {
        match_field: rule.match_field,
        match_type: rule.match_type,
        match_value: rule.match_value,
        institution_scope: rule.institution_scope,
      })
    ) {
      includedMatched += 1;
    }
  }

  const excludedStillMatched = excluded.filter((t) =>
    txMatchesRule(t, {
      match_field: rule.match_field,
      match_type: rule.match_type,
      match_value: rule.match_value,
      institution_scope: rule.institution_scope,
    }),
  );

  let warning: string | null = null;
  if (excludedStillMatched.length > 0) {
    const labels = excludedStillMatched
      .slice(0, 3)
      .map((t) => t.merchant || t.description || t.id)
      .join(", ");
    warning =
      `This rule would still match ${excludedStillMatched.length} transaction(s) you excluded` +
      (labels ? ` (e.g. ${labels})` : "") +
      ". Tighten the match text, or leave them as manual overrides so future rule runs skip them.";
  } else if (included.length > 0 && includedMatched < included.length) {
    warning =
      `This rule only matches ${includedMatched} of ${included.length} transactions you assigned. ` +
      "Consider a broader match value, or save separate rules.";
  }

  return {
    includedMatched,
    includedTotal: included.length,
    excludedStillMatched,
    warning,
    plainEnglish,
  };
}

/**
 * Prefer a match value common to included labels and, when possible, not matching excluded.
 */
export function refineMatchValueFromEvidence(
  base: RuleSuggestion,
  included: Transaction[],
  excluded: Transaction[],
): RuleSuggestion {
  if (!included.length) return base;

  const labels = included
    .map((t) => {
      if (base.match_field === "merchant") return (t.merchant || "").trim();
      if (base.match_field === "description") return (t.description || "").trim();
      if (base.match_field === "original_description")
        return (t.original_description || "").trim();
      return (t.merchant || t.description || "").trim();
    })
    .filter(Boolean);

  if (!labels.length) return base;

  // Longest common substring (case-insensitive) of short labels — practical for merchant names.
  let lcs = labels[0].toLowerCase();
  for (let i = 1; i < labels.length; i++) {
    lcs = longestCommonSubstring(lcs, labels[i].toLowerCase());
    if (lcs.length < 3) break;
  }

  let candidate = (lcs.length >= 3 ? lcs : labels[0]).trim();
  // Prefer original casing from first label
  const fromFirst = labels[0];
  const idx = fromFirst.toLowerCase().indexOf(candidate.toLowerCase());
  if (idx >= 0) {
    candidate = fromFirst.slice(idx, idx + candidate.length);
  }

  // If contains still hits exclusions, try exact on most common full label
  let suggestion: RuleSuggestion = {
    ...base,
    match_type: "contains",
    match_value: candidate,
  };

  const stillHit = excluded.some((t) =>
    txMatchesRule(t, {
      match_field: suggestion.match_field,
      match_type: suggestion.match_type,
      match_value: suggestion.match_value,
      institution_scope: suggestion.institution_scope,
    }),
  );

  if (stillHit && labels.length === 1) {
    suggestion = {
      ...base,
      match_type: "exact",
      match_value: labels[0],
    };
  } else if (stillHit) {
    // Shorten not helping — keep contains but leave warning to UI
    suggestion = {
      ...base,
      match_type: "contains",
      match_value: candidate,
    };
  }

  return suggestion;
}

function longestCommonSubstring(a: string, b: string): string {
  if (!a || !b) return "";
  const m = a.length;
  const n = b.length;
  let best = "";
  const dp: number[] = new Array(n + 1).fill(0);
  for (let i = 1; i <= m; i++) {
    let prev = 0;
    for (let j = 1; j <= n; j++) {
      const tmp = dp[j];
      if (a[i - 1] === b[j - 1]) {
        dp[j] = prev + 1;
        if (dp[j] > best.length) {
          best = a.slice(i - dp[j], i);
        }
      } else {
        dp[j] = 0;
      }
      prev = tmp;
    }
  }
  return best.trim();
}
