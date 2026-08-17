/**
 * Self-test for Spending next honesty chips (quiet vs ≥70 card).
 * Run: npx --yes tsx src/features/spending-next/honestyChips.selftest.ts  (from frontend/)
 */
import { honestyChips } from "./honestyChips";

function assertEq(actual: unknown, expected: unknown, msg: string): void {
  if (actual !== expected) {
    throw new Error(`${msg}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

function kinds(model: ReturnType<typeof honestyChips>): string[] {
  return model.chips.map((c) => c.kind);
}

const none = honestyChips({
  internalTransferCount: 0,
  unconvertedCount: 0,
  uncategorizedPct: 0,
});
assertEq(none.chips.length, 0, "all zero → no chips");
assertEq(none.uncatCard, false, "0% → no uncat card");

const internalsOnly = honestyChips({
  internalTransferCount: 3,
  unconvertedCount: 0,
  uncategorizedPct: 10,
});
assertEq(kinds(internalsOnly).join(","), "internals", "internals only if > 0");
assertEq(
  internalsOnly.chips[0]?.label,
  "3 internals excluded",
  "internals label",
);

const noInternals = honestyChips({
  internalTransferCount: 0,
  unconvertedCount: 2,
  uncategorizedPct: 10,
});
assertEq(kinds(noInternals).includes("internals"), false, "internals 0 → no chip");

const unconvertedOnly = honestyChips({
  internalTransferCount: 0,
  unconvertedCount: 4,
  uncategorizedPct: 5,
});
assertEq(kinds(unconvertedOnly).join(","), "unconverted", "unconverted only if > 0");
assertEq(unconvertedOnly.chips[0]?.label, "4 unconverted", "unconverted label");

const noUnconverted = honestyChips({
  internalTransferCount: 1,
  unconvertedCount: 0,
  uncategorizedPct: 5,
});
assertEq(
  kinds(noUnconverted).includes("unconverted"),
  false,
  "unconverted 0 → no chip",
);

const quietLow = honestyChips({ uncategorizedPct: 20 });
assertEq(kinds(quietLow).includes("uncat"), true, "20% → quiet uncat chip");
assertEq(quietLow.uncatCard, false, "20% → not the card");

const quietHigh = honestyChips({ uncategorizedPct: 69.9 });
assertEq(kinds(quietHigh).includes("uncat"), true, "69.9% → quiet uncat chip");
assertEq(quietHigh.uncatCard, false, "69.9% → not the card");

const justUnder = honestyChips({ uncategorizedPct: 19.9 });
assertEq(kinds(justUnder).includes("uncat"), false, "19.9% → no uncat chip");
assertEq(justUnder.uncatCard, false, "19.9% → no card");

const card70 = honestyChips({ uncategorizedPct: 70 });
assertEq(kinds(card70).includes("uncat"), false, "≥70 is card not quiet chip");
assertEq(card70.uncatCard, true, "70% → card");

const cardHigh = honestyChips({
  internalTransferCount: 2,
  unconvertedCount: 1,
  uncategorizedPct: 88,
});
assertEq(kinds(cardHigh).includes("uncat"), false, "88% → no quiet uncat chip");
assertEq(cardHigh.uncatCard, true, "88% → card");
assertEq(kinds(cardHigh).includes("internals"), true, "88% still shows internals");
assertEq(kinds(cardHigh).includes("unconverted"), true, "88% still shows unconverted");

console.log("honestyChips.selftest: ok");
