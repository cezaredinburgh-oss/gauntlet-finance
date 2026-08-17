/**
 * Self-test for Categorize next workspace mode (query-driven Review / Rules / Categories).
 * Run: npx --yes tsx src/features/categorize-next/workspaceMode.selftest.ts  (from frontend/)
 */
import {
  applyWorkspaceMode,
  isGrokPlusOverlay,
  modeFromSearchParams,
  workspaceModeParamPatch,
} from "./workspaceMode";

function assertEq(actual: unknown, expected: unknown, msg: string): void {
  if (actual !== expected) {
    throw new Error(`${msg}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

assertEq(
  modeFromSearchParams(new URLSearchParams("mode=rules")),
  "rules",
  "mode=rules wins",
);
assertEq(
  modeFromSearchParams(new URLSearchParams("mode=rules&panel=grokplus")),
  "rules",
  "mode=rules wins over panel",
);
assertEq(
  modeFromSearchParams(new URLSearchParams("mode=categories")),
  "categories",
  "mode=categories wins",
);
assertEq(
  modeFromSearchParams(new URLSearchParams("panel=rules")),
  "rules",
  "panel=rules → rules",
);
assertEq(
  modeFromSearchParams(new URLSearchParams("panel=grokplus")),
  "review",
  "panel=grokplus returns review",
);
assertEq(
  isGrokPlusOverlay(new URLSearchParams("panel=grokplus")),
  true,
  "panel=grokplus is Review overlay",
);
assertEq(
  modeFromSearchParams(new URLSearchParams()),
  "review",
  "missing → review",
);
assertEq(
  modeFromSearchParams(new URLSearchParams("mode=nope")),
  "review",
  "invalid mode → review (unless panel=rules)",
);

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
assertEq(toReview.get("mode"), null, "review omits mode");
assertEq(toReview.get("panel"), null, "review clears panel");

const patch = workspaceModeParamPatch("categories");
assertEq(patch.mode, "categories", "categories patch writes mode");
assertEq(patch.panel, null, "categories patch clears panel");

console.log("workspaceMode.selftest: ok");
