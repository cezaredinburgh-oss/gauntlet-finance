/**
 * Self-test for cost-visibility / Y-domain helpers.
 * Run: npx --yes tsx src/lib/chartCostVisibility.selftest.ts  (from frontend/)
 */
import {
  COST_DOMAIN_PAD,
  COST_FLAT_REL_EPS,
  COST_MIN_SPAN_FRACTION,
  chartYDomain,
  shouldShowCostBasis,
} from "./chartCostVisibility";

function assert(cond: unknown, msg: string): asserts cond {
  if (!cond) throw new Error(msg);
}

function almost(a: number, b: number, eps = 1e-9): boolean {
  return Math.abs(a - b) <= eps;
}

function inClosed(x: number, lo: number, hi: number): boolean {
  return x >= lo && x <= hi;
}

// --- shouldShowCostBasis ---

assert(shouldShowCostBasis(101.8, [101.1, 102.4]), "inside band → show");
assert(shouldShowCostBasis(35, [40, 80, 120]), "near band → show");

// 1× gap: pRange=10, cost 10 below → share 50%
assert(shouldShowCostBasis(90, [100, 110]), "1× gap → show");
assert(shouldShowCostBasis(120, [100, 110]), "1× gap above → show");

// 2× gap: pRange=10, cost 20 below → share 33% < 35%
assert(!shouldShowCostBasis(80, [100, 110]), "2× gap → hide");
assert(!shouldShowCostBasis(130, [100, 110]), "2× gap above → hide");
assert(!shouldShowCostBasis(40_000, [96_800, 97_200]), "far cost → hide");
// Tight RTH band + wild pre print: cost follows RTH y-span only.
assert(
  shouldShowCostBasis(40_000, [40_000, 96_800, 97_200]),
  "including pre would show — caller must pass RTH y's",
);
assert(
  !shouldShowCostBasis(40_000, [96_800, 97_200]),
  "tight RTH band hides cost even if pre wicked toward it",
);

assert(!shouldShowCostBasis(80, [50, 50, 50]), "flat+far → hide");
assert(shouldShowCostBasis(50, [50, 50]), "flat+equal → show");
assert(shouldShowCostBasis(50.1, [50]), "flat+near → show");

const flatScale = 50;
assert(
  shouldShowCostBasis(flatScale + flatScale * COST_FLAT_REL_EPS * 0.5, [flatScale]),
  "flat inside eps → show",
);
assert(
  !shouldShowCostBasis(flatScale + flatScale * COST_FLAT_REL_EPS * 2, [flatScale]),
  "flat outside eps → hide",
);

assert(!shouldShowCostBasis(Number.NaN, [1, 2]), "NaN cost → hide");
assert(!shouldShowCostBasis(Number.POSITIVE_INFINITY, [1, 2]), "Inf cost → hide");
assert(!shouldShowCostBasis(10, []), "empty values → hide");
assert(
  !shouldShowCostBasis(10, [Number.NaN, Number.POSITIVE_INFINITY]),
  "non-finite values → hide",
);

// --- chartYDomain ---

const hiddenCost = 40_000;
const tight = [96_800, 97_200];
assert(!shouldShowCostBasis(hiddenCost, tight), "precondition hide");
const hiddenDom = chartYDomain(tight, {
  cost: hiddenCost,
  showCost: false,
  pad: COST_DOMAIN_PAD,
});
assert(!inClosed(hiddenCost, hiddenDom[0], hiddenDom[1]), "hidden cost absent from domain");
assert(almost(hiddenDom[0], 96_800 - 16), `hidden lo ${hiddenDom[0]}`);
assert(almost(hiddenDom[1], 97_200 + 16), `hidden hi ${hiddenDom[1]}`);

const shownCost = 35;
const wide = [40, 120];
assert(shouldShowCostBasis(shownCost, wide), "precondition show");
const shownDom = chartYDomain(wide, {
  cost: shownCost,
  showCost: true,
  pad: COST_DOMAIN_PAD,
});
assert(inClosed(shownCost, shownDom[0], shownDom[1]), "shown cost inside domain");

// Closest hidden cost is ~1.86× pRange away; 4% pad cannot reach it.
const pMin = 100;
const pMax = 110;
const pRange = pMax - pMin;
const justHidden = pMax - pRange / COST_MIN_SPAN_FRACTION - 0.01;
assert(!shouldShowCostBasis(justHidden, [pMin, pMax]), "just past 35% → hide");
const justDom = chartYDomain([pMin, pMax], {
  cost: justHidden,
  showCost: false,
  pad: COST_DOMAIN_PAD,
});
assert(justHidden < justDom[0], "4% pad does not re-introduce a hidden cost");

const emptyDom = chartYDomain([], { showCost: false });
assert(emptyDom[0] === 0 && emptyDom[1] === 1, "empty domain");

const exp = chartYDomain([100, 110], { cost: 90, showCost: true, pad: COST_DOMAIN_PAD });
assert(almost(exp[0], 89.2), `expand lo ${exp[0]}`);
assert(almost(exp[1], 110.8), `expand hi ${exp[1]}`);
assert(inClosed(90, exp[0], exp[1]), "shown extreme cost stays inside padded domain");

const ignored = chartYDomain([100, 110], { cost: 40_000, showCost: false });
assert(!inClosed(40_000, ignored[0], ignored[1]), "cost ignored when showCost is false");

console.log("chartCostVisibility.selftest: ok");
