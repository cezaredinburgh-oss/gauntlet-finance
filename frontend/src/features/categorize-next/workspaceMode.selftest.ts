/**
 * Self-test for Categorize next URL contract (hub / windows / inbound txs).
 * Run: npx --yes tsx src/features/categorize-next/workspaceMode.selftest.ts  (from frontend/)
 */
import {
  applyWorkspaceMode,
  categorizeHref,
  hasListScope,
  isGrokPlusOverlay,
  modeFromSearchParams,
  screenFromSearchParams,
  windowParamPatch,
  workspaceModeParamPatch,
} from "./workspaceMode";

function assertEq(actual: unknown, expected: unknown, msg: string): void {
  if (actual !== expected) {
    throw new Error(`${msg}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

function assertTrue(cond: boolean, msg: string): void {
  if (!cond) throw new Error(msg);
}

// --- screenFromSearchParams ---

assertEq(
  screenFromSearchParams(new URLSearchParams()),
  "hub",
  "bare path → hub",
);
assertEq(
  screenFromSearchParams(new URLSearchParams("mode=review")),
  "review",
  "mode=review → leftovers",
);
assertEq(
  screenFromSearchParams(new URLSearchParams("mode=rules")),
  "rules",
  "mode=rules wins",
);
assertEq(
  screenFromSearchParams(new URLSearchParams("mode=rules&panel=grokplus")),
  "rules",
  "mode=rules wins over panel=grokplus",
);
assertEq(
  screenFromSearchParams(new URLSearchParams("mode=categories")),
  "categories",
  "mode=categories wins",
);
assertEq(
  screenFromSearchParams(new URLSearchParams("panel=rules")),
  "rules",
  "panel=rules without mode → rules",
);
assertEq(
  screenFromSearchParams(new URLSearchParams("panel=grokplus")),
  "grokplus",
  "panel=grokplus without mode → grokplus",
);
assertEq(
  screenFromSearchParams(new URLSearchParams("mode=txs")),
  "txs",
  "mode=txs → txs",
);
assertEq(
  screenFromSearchParams(new URLSearchParams("mode=nope")),
  "hub",
  "invalid mode → hub",
);

// hasListScope inbound → txs (skip hub)
assertEq(
  screenFromSearchParams(new URLSearchParams("date_from=2026-01-01")),
  "txs",
  "date_from → txs",
);
assertEq(
  screenFromSearchParams(new URLSearchParams("date_to=2026-01-31")),
  "txs",
  "date_to → txs",
);
assertEq(
  screenFromSearchParams(new URLSearchParams("category_id=uncategorized")),
  "txs",
  "category_id → txs",
);
assertEq(
  screenFromSearchParams(new URLSearchParams("hide_transfers=1")),
  "txs",
  "hide_transfers=1 → txs",
);
assertEq(
  screenFromSearchParams(new URLSearchParams("hide_transfers=0")),
  "txs",
  "hide_transfers=0 → txs",
);
assertEq(
  screenFromSearchParams(new URLSearchParams("q=coffee")),
  "txs",
  "q → txs",
);
assertEq(
  screenFromSearchParams(new URLSearchParams("tx=abc-uuid")),
  "txs",
  "tx= alone → txs",
);
assertEq(
  screenFromSearchParams(
    new URLSearchParams(
      "date_from=2026-01-01&hide_transfers=1&expenses_only=1&category_id=",
    ),
  ),
  "txs",
  "Spending-style inbound → txs",
);

assertTrue(
  hasListScope(new URLSearchParams("category_id=uncategorized")),
  "hasListScope category_id",
);
assertTrue(
  hasListScope(new URLSearchParams("q=shop")),
  "hasListScope q",
);
assertTrue(
  hasListScope(new URLSearchParams("tx=1")),
  "hasListScope tx",
);
assertTrue(
  !hasListScope(new URLSearchParams()),
  "bare path has no list scope",
);
assertTrue(
  !hasListScope(new URLSearchParams("panel=grokplus")),
  "panel=grokplus is not list scope",
);

// Drill keys overlay any window
assertEq(
  screenFromSearchParams(new URLSearchParams("mode=review&focus=id1")),
  "txs",
  "focus= overlays leftovers → txs",
);
assertEq(
  screenFromSearchParams(new URLSearchParams("vendor=m:shop")),
  "txs",
  "vendor= → txs",
);
assertEq(
  screenFromSearchParams(new URLSearchParams("rule=rule-id")),
  "txs",
  "rule= → txs",
);

// Tab helper still maps grokplus / hub / txs → review for the tablist
assertEq(
  modeFromSearchParams(new URLSearchParams("mode=rules&panel=grokplus")),
  "rules",
  "tab helper: mode=rules wins over panel",
);
assertEq(
  modeFromSearchParams(new URLSearchParams("panel=grokplus")),
  "review",
  "tab helper: grokplus highlights Review",
);
assertEq(
  isGrokPlusOverlay(new URLSearchParams("panel=grokplus")),
  true,
  "panel=grokplus is overlay",
);

// --- writes ---

const cleared = applyWorkspaceMode(
  new URLSearchParams("mode=review&panel=grokplus&q=coffee"),
  "rules",
);
assertEq(cleared.get("mode"), "rules", "setWorkspaceMode writes mode=rules");
assertEq(cleared.get("panel"), null, "setWorkspaceMode clears panel");
assertEq(cleared.get("q"), "coffee", "setWorkspaceMode keeps other params");

const toReview = applyWorkspaceMode(
  new URLSearchParams("mode=rules&panel=rules"),
  "review",
);
assertEq(toReview.get("mode"), "review", "review writes mode=review (not omit)");
assertEq(toReview.get("panel"), null, "review clears panel");

const catPatch = workspaceModeParamPatch("categories");
assertEq(catPatch.mode, "categories", "categories patch writes mode");
assertEq(catPatch.panel, null, "categories patch clears panel");

const reviewPatch = windowParamPatch("review");
assertEq(reviewPatch.mode, "review", "window review writes mode=review");
assertEq(reviewPatch.panel, null, "window review clears panel");

const grokPatch = windowParamPatch("grokplus");
assertEq(grokPatch.mode, null, "window grokplus omits mode");
assertEq(grokPatch.panel, "grokplus", "window grokplus writes panel");

const txsPatch = windowParamPatch("txs");
assertEq(txsPatch.mode, "txs", "window txs writes mode=txs");
assertEq(txsPatch.panel, null, "window txs clears panel");

assertEq(
  categorizeHref(windowParamPatch("review")),
  "/expenses/categorize?mode=review",
  "review href",
);
assertEq(
  categorizeHref(windowParamPatch("grokplus")),
  "/expenses/categorize?panel=grokplus",
  "grokplus href",
);
assertEq(
  categorizeHref(windowParamPatch("txs")),
  "/expenses/categorize?mode=txs",
  "browse txs href",
);

console.log("workspaceMode.selftest: ok");
