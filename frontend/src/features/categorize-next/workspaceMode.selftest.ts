/**
 * Self-test for Categorize next URL contract (hub / windows / inbound txs).
 * Run: npx --yes tsx src/features/categorize-next/workspaceMode.selftest.ts  (from frontend/)
 */
import {
  applyParamPatch,
  applyWorkspaceMode,
  categorizeHref,
  chooseAllowlistWrite,
  drillParamPatch,
  FOCUS_MAX_CHARS,
  hasListScope,
  isGrokPlusOverlay,
  modeFromSearchParams,
  parseFocusIds,
  screenFromSearchParams,
  shouldRestoreNextStepsFromSimilar,
  undrillParamPatch,
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

// --- PR2: focus overlay + undrill ---

assertEq(
  screenFromSearchParams(new URLSearchParams("focus=id-a,id-b")),
  "txs",
  "focus= ⇒ screen txs",
);
assertEq(
  screenFromSearchParams(
    new URLSearchParams("mode=review&src=review&focus=seed,sim1"),
  ),
  "txs",
  "reviewing_similar + focus= ⇒ txs not leftovers",
);
assertEq(
  screenFromSearchParams(new URLSearchParams("panel=grokplus&focus=id1")),
  "txs",
  "focus= overlays grokplus → txs",
);
assertEq(
  screenFromSearchParams(new URLSearchParams("focus_key=k1")),
  "txs",
  "focus_key= → txs",
);

const similarDrill = drillParamPatch({
  src: "review",
  focus: ["seed-1", "sim-1", "sim-2"],
});
assertEq(similarDrill.mode, "txs", "similar drill writes mode=txs");
assertEq(similarDrill.src, "review", "similar drill writes src=review");
assertEq(similarDrill.focus, "seed-1,sim-1,sim-2", "similar drill writes seed+similar");
assertEq(similarDrill.panel, null, "similar drill clears panel");

const similarParams = applyParamPatch(
  new URLSearchParams("mode=review"),
  similarDrill,
);
assertEq(
  screenFromSearchParams(similarParams),
  "txs",
  "after similar drill URL is txs",
);

const similarUndrill = applyParamPatch(similarParams, undrillParamPatch(similarParams));
assertEq(
  screenFromSearchParams(similarUndrill),
  "review",
  "undrill after similar → leftovers",
);
assertEq(similarUndrill.get("focus"), null, "undrill drops focus");
assertEq(similarUndrill.get("src"), null, "undrill drops src");
assertEq(similarUndrill.get("mode"), "review", "undrill restores mode=review");

// history.back from similar: push is undone by the browser (no undrillParamPatch).
// Page popstate/effect must restore next_steps when this is true.
const afterBack = new URLSearchParams("mode=review");
assertEq(screenFromSearchParams(afterBack), "review", "history.back lands leftovers");
assertTrue(
  shouldRestoreNextStepsFromSimilar(
    "reviewing_similar",
    screenFromSearchParams(afterBack),
    afterBack,
  ),
  "history.back from similar → restore next_steps",
);
assertTrue(
  !shouldRestoreNextStepsFromSimilar(
    "reviewing_similar",
    screenFromSearchParams(similarParams),
    similarParams,
  ),
  "still on similar txs → do not restore yet",
);
assertTrue(
  !shouldRestoreNextStepsFromSimilar("next_steps", "review", afterBack),
  "already next_steps → do not restore again",
);
assertTrue(
  !shouldRestoreNextStepsFromSimilar("idle", "review", afterBack),
  "idle leftovers → do not enter next_steps",
);

function assertUndrillKeeps(
  start: string,
  keep: Record<string, string>,
  expectMode: string | null,
  expectPanel: string | null,
  gone: string[],
  msg: string,
): void {
  const params = new URLSearchParams(start);
  for (const [k, v] of Object.entries(keep)) params.set(k, v);
  const next = applyParamPatch(params, undrillParamPatch(params));
  assertEq(next.get("mode"), expectMode, `${msg} mode`);
  assertEq(next.get("panel"), expectPanel, `${msg} panel`);
  for (const key of gone) {
    assertEq(next.get(key), null, `${msg} drops ${key}`);
  }
  for (const [k, v] of Object.entries(keep)) {
    assertEq(next.get(k), v, `${msg} keeps ${k}`);
  }
}

assertUndrillKeeps(
  "mode=txs&src=review&focus=id1&vendor=m:shop&focus_key=k&tx=t1",
  { q: "coffee", date_from: "2026-01-01" },
  "review",
  null,
  ["focus", "vendor", "focus_key", "tx", "src"],
  "undrill src=review",
);
assertUndrillKeeps(
  "mode=txs&src=grokplus&focus=id1",
  { q: "x" },
  null,
  "grokplus",
  ["focus", "src"],
  "undrill src=grokplus",
);
assertUndrillKeeps(
  "mode=txs&src=rules&rule=r1&hide_transfers=0",
  { q: "keep" },
  "rules",
  null,
  ["rule", "hide_transfers", "src"],
  "undrill src=rules drops hide_transfers (DRILL_WRITES)",
);
assertUndrillKeeps(
  "mode=txs&src=categories&category_id=c1&category_ids=c1,c2",
  { q: "keep" },
  "categories",
  null,
  ["category_id", "category_ids", "src"],
  "undrill src=categories",
);
assertUndrillKeeps(
  "mode=txs&src=hub&category_id=uncategorized",
  { q: "keep" },
  null,
  null,
  ["category_id", "src"],
  "undrill src=hub",
);
assertUndrillKeeps(
  "mode=txs&src=hub_usd&category_id=uncategorized&expenses_only=1",
  { q: "keep" },
  null,
  null,
  ["category_id", "expenses_only", "src"],
  "undrill src=hub_usd",
);

const grokWrite = chooseAllowlistWrite({
  ids: ["a", "b"],
  src: "grokplus",
  fetchedMissing: true,
});
assertEq(grokWrite.type, "focus", "short grokplus allowlist uses focus=");

const longIds = Array.from({ length: 80 }, (_, i) => `00000000-0000-0000-0000-00000000${String(i).padStart(4, "0")}`);
assertTrue(
  longIds.join(",").length > FOCUS_MAX_CHARS,
  "fixture exceeds focus max",
);
const leftoverOverflow = chooseAllowlistWrite({
  ids: longIds,
  src: "review",
  leftoverVendorKey: "m:shop",
  fetchedMissing: false,
});
assertEq(leftoverOverflow.type, "vendor", "leftover overflow without fetch → vendor=");
if (leftoverOverflow.type === "vendor") {
  assertEq(leftoverOverflow.vendor, "m:shop", "vendor key passthrough");
}

const unlabeledOverflow = chooseAllowlistWrite({
  ids: longIds,
  src: "review",
  leftoverVendorKey: "none",
  fetchedMissing: false,
});
assertEq(unlabeledOverflow.type, "focus_key", "leftover key none cannot reconstruct via vendor=");

const leftoverFetched = chooseAllowlistWrite({
  ids: longIds,
  src: "review",
  leftoverVendorKey: "m:shop",
  fetchedMissing: true,
});
assertEq(leftoverFetched.type, "focus_key", "leftover overflow after extra fetch → focus_key");

const grokOverflow = chooseAllowlistWrite({
  ids: longIds,
  src: "grokplus",
  leftoverVendorKey: "m:shop",
  fetchedMissing: false,
});
assertEq(grokOverflow.type, "focus_key", "Grok+ overflow never uses vendor=");

assertEq(parseFocusIds("a, b, ,c").join("|"), "a|b|c", "parseFocusIds trims");
assertEq(parseFocusIds("").length, 0, "parseFocusIds empty");

console.log("workspaceMode.selftest: ok");
