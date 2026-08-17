/**
 * Self-test for Alerts next domain board (collapse empty; filter in-memory).
 * Run: npx --yes tsx src/features/alerts-next/domainBoard.selftest.ts  (from frontend/)
 */
import type { AlertItem } from "../../api/types";
import { groupAlertsByDomain, visibleDomains } from "./domainBoard";

function assertEq(actual: unknown, expected: unknown, msg: string): void {
  if (actual !== expected) {
    throw new Error(`${msg}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

function assertDeep(actual: unknown, expected: unknown, msg: string): void {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) throw new Error(`${msg}: expected ${e}, got ${a}`);
}

function item(
  over: Partial<AlertItem> & Pick<AlertItem, "id" | "domain">,
): AlertItem {
  return {
    title: over.title ?? over.id,
    body: over.body ?? "",
    level: over.level ?? "info",
    href: over.href,
    domain: over.domain,
    id: over.id,
  };
}

const empty = groupAlertsByDomain([]);
assertDeep(visibleDomains(empty, "all"), [], "all empty → no columns");
assertDeep(visibleDomains(empty, "crypto"), [], "filter crypto when empty → []");

const spendOnly = groupAlertsByDomain([
  item({ id: "uncat", domain: "spending", level: "warn" }),
]);
assertEq(spendOnly.spending.length, 1, "spending-only: spending has 1");
assertEq(spendOnly.stocks.length, 0, "spending-only: stocks empty");
assertEq(spendOnly.crypto.length, 0, "spending-only: crypto empty");
assertDeep(visibleDomains(spendOnly, "all"), ["spending"], "spending-only → [spending]");
assertDeep(
  visibleDomains(spendOnly, "crypto"),
  [],
  "filter crypto when crypto empty → []",
);
assertDeep(
  visibleDomains(spendOnly, "spending"),
  ["spending"],
  "filter spending when present → [spending]",
);

const mixed = groupAlertsByDomain([
  item({ id: "info-spend", domain: "spending", level: "info" }),
  item({ id: "danger-spend", domain: "spending", level: "danger" }),
  item({ id: "warn-stock", domain: "stocks", level: "warn" }),
  item({
    id: "tax",
    domain: "stocks",
    level: "opportunity",
    href: "/investments?focus=tax_runway",
  }),
]);
assertDeep(
  visibleDomains(mixed, "all"),
  ["spending", "stocks"],
  "mixed: empty crypto omitted; order spending then stocks",
);
assertDeep(visibleDomains(mixed, "stocks"), ["stocks"], "filter stocks → [stocks]");
assertDeep(mixed.spending.map((a) => a.id), ["danger-spend", "info-spend"], "rank: danger before info");
assertEq(
  mixed.stocks[1]?.href,
  "/investments?focus=tax_runway",
  "href including focus=tax_runway is not rewritten",
);

console.log("domainBoard.selftest: ok");
