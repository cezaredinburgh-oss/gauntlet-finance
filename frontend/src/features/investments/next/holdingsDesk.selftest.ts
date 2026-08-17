/**
 * Self-test for lab-only holdings desk resolution.
 * Run: npx --yes tsx src/features/investments/next/holdingsDesk.selftest.ts  (from frontend/)
 */
import {
  HOLDINGS_DESK_DEFAULT,
  HOLDINGS_DESK_KEY,
  loadPersistedDesk,
  mergeDeskParam,
  resolveHoldingsDesk,
  savePersistedDesk,
  type DeskStorage,
  type HoldingsDesk,
} from "./holdingsDesk";

type MemoryStorage = DeskStorage & { writes: Array<[string, string]> };

function memoryStorage(initial: Record<string, string> = {}): MemoryStorage {
  const data = new Map<string, string>(Object.entries(initial));
  const writes: Array<[string, string]> = [];
  return {
    writes,
    getItem(key: string) {
      return data.has(key) ? (data.get(key) as string) : null;
    },
    setItem(key: string, value: string) {
      writes.push([key, value]);
      data.set(key, value);
    },
  };
}

const lab = { is_demo: true, demo_kind: "lab" } as const;
const owner = { is_demo: false, demo_kind: null };
const sandbox = { is_demo: true, demo_kind: "sandbox" } as const;
const tour = { is_demo: true, demo_kind: "tour" } as const;

function params(search = ""): URLSearchParams {
  return new URLSearchParams(search);
}

function assertEq(actual: unknown, expected: unknown, msg: string): void {
  if (actual !== expected) {
    throw new Error(`${msg}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

for (const [label, user] of [
  ["owner", owner],
  ["sandbox", sandbox],
  ["tour", tour],
  ["null", null],
] as const) {
  const store = memoryStorage();
  const desk = resolveHoldingsDesk(user, params("desk=next"), store);
  assertEq(desk, "classic", `${label} must ignore ?desk=next`);
  assertEq(store.writes.length, 0, `${label} resolve must not write storage`);
}

assertEq(
  resolveHoldingsDesk(lab, params("desk=next"), memoryStorage()),
  "next",
  "lab + ?desk=next",
);
assertEq(
  resolveHoldingsDesk(lab, params("desk=classic"), memoryStorage()),
  "classic",
  "lab + ?desk=classic",
);
assertEq(
  resolveHoldingsDesk(lab, params("desk=foo"), memoryStorage()),
  HOLDINGS_DESK_DEFAULT,
  "lab + ?desk=foo → default",
);
assertEq(HOLDINGS_DESK_DEFAULT, "next", "PR3 default is next");

assertEq(
  resolveHoldingsDesk(lab, params(), memoryStorage()),
  "next",
  "lab + no query + no persist → next",
);

const persistNext = memoryStorage({ [HOLDINGS_DESK_KEY]: "next" });
assertEq(
  resolveHoldingsDesk(lab, params(), persistNext),
  "next",
  "lab + no query + persist next",
);
assertEq(persistNext.writes.length, 0, "persist fallback must not write");

const persistClassic = memoryStorage({ [HOLDINGS_DESK_KEY]: "classic" });
assertEq(
  resolveHoldingsDesk(lab, params("desk=foo"), persistClassic),
  "classic",
  "lab + invalid query uses persist",
);

const queryBeatsPersist = memoryStorage({ [HOLDINGS_DESK_KEY]: "classic" });
assertEq(
  resolveHoldingsDesk(lab, params("desk=next"), queryBeatsPersist),
  "next",
  "lab query beats persist",
);
assertEq(queryBeatsPersist.writes.length, 0, "query path must not persist");

const writeProbe = memoryStorage();
resolveHoldingsDesk(lab, params("desk=next"), writeProbe);
resolveHoldingsDesk(lab, params(), writeProbe);
resolveHoldingsDesk(owner, params("desk=next"), writeProbe);
assertEq(writeProbe.writes.length, 0, "resolve must not write localStorage");

const saved = memoryStorage();
savePersistedDesk("next", saved);
assertEq(saved.writes.length, 1, "save writes once");
assertEq(saved.writes[0][0], HOLDINGS_DESK_KEY, "save uses holdings desk key");
assertEq(saved.writes[0][1], "next", "save writes next");
assertEq(loadPersistedDesk(saved), "next", "load reads saved desk");
assertEq(
  loadPersistedDesk(memoryStorage({ [HOLDINGS_DESK_KEY]: "nope" })),
  null,
  "load rejects invalid persist",
);

const mergedRunway = mergeDeskParam(params("focus=tax_runway"), "classic");
assertEq(mergedRunway.get("focus"), "tax_runway", "merge keeps focus=tax_runway");
assertEq(mergedRunway.get("desk"), "classic", "merge sets desk=classic");

const mergedPrices = mergeDeskParam(params("focus=prices&ticker=AAPL"), "next");
assertEq(mergedPrices.get("focus"), "prices", "merge keeps focus=prices");
assertEq(mergedPrices.get("ticker"), "AAPL", "merge keeps other params");
assertEq(mergedPrices.get("desk"), "next", "merge sets desk=next");

const untouched: HoldingsDesk = "classic";
const source = params("focus=tax_runway");
mergeDeskParam(source, untouched);
assertEq(source.get("desk"), null, "merge does not mutate the source params");
assertEq(source.get("focus"), "tax_runway", "source focus unchanged");

console.log("holdingsDesk.selftest: ok");
