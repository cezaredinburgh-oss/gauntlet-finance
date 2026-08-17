/**
 * Self-test for lab-only Analysis/DCA/Tax desk resolution.
 * Run: npx --yes tsx src/auth/labDesk.selftest.ts  (from frontend/)
 */
import {
  ANALYSIS_DESK,
  DCA_DESK,
  TAX_DESK,
  loadLabDesk,
  mergeDeskParam,
  resolveLabDesk,
  saveLabDesk,
  type DeskStorage,
  type LabDesk,
} from "./labDesk";

const HOLDINGS_DESK_KEY = "gauntlet.holdings.desk";

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
  const desk = resolveLabDesk(user, params("desk=next"), ANALYSIS_DESK, store);
  assertEq(desk, "classic", `${label} must ignore ?desk=next`);
  assertEq(store.writes.length, 0, `${label} resolve must not write storage`);
}

assertEq(
  resolveLabDesk(lab, params("desk=next"), ANALYSIS_DESK, memoryStorage()),
  "next",
  "lab + ?desk=next",
);
assertEq(
  resolveLabDesk(lab, params("desk=classic"), ANALYSIS_DESK, memoryStorage()),
  "classic",
  "lab + ?desk=classic",
);
assertEq(
  resolveLabDesk(lab, params("desk=foo"), ANALYSIS_DESK, memoryStorage()),
  ANALYSIS_DESK.defaultDesk,
  "lab + ?desk=foo → default",
);
assertEq(ANALYSIS_DESK.defaultDesk, "next", "analysis default is next");
assertEq(DCA_DESK.defaultDesk, "next", "dca default is next");
assertEq(TAX_DESK.defaultDesk, "next", "tax default is next");

assertEq(
  resolveLabDesk(lab, params(), ANALYSIS_DESK, memoryStorage()),
  "next",
  "lab + no query + no persist → next",
);

const persistNext = memoryStorage({ [ANALYSIS_DESK.persistKey]: "next" });
assertEq(
  resolveLabDesk(lab, params(), ANALYSIS_DESK, persistNext),
  "next",
  "lab + no query + persist next",
);
assertEq(persistNext.writes.length, 0, "persist fallback must not write");

const persistClassic = memoryStorage({ [ANALYSIS_DESK.persistKey]: "classic" });
assertEq(
  resolveLabDesk(lab, params("desk=foo"), ANALYSIS_DESK, persistClassic),
  "classic",
  "lab + invalid query uses persist",
);

const queryBeatsPersist = memoryStorage({ [ANALYSIS_DESK.persistKey]: "classic" });
assertEq(
  resolveLabDesk(lab, params("desk=next"), ANALYSIS_DESK, queryBeatsPersist),
  "next",
  "lab query beats persist",
);
assertEq(queryBeatsPersist.writes.length, 0, "query path must not persist");

const writeProbe = memoryStorage({ [HOLDINGS_DESK_KEY]: "classic" });
resolveLabDesk(lab, params("desk=next"), ANALYSIS_DESK, writeProbe);
resolveLabDesk(lab, params(), ANALYSIS_DESK, writeProbe);
resolveLabDesk(owner, params("desk=next"), ANALYSIS_DESK, writeProbe);
assertEq(writeProbe.writes.length, 0, "resolve must not write localStorage");
assertEq(
  writeProbe.getItem(HOLDINGS_DESK_KEY),
  "classic",
  "resolve must not touch gauntlet.holdings.desk",
);

const saved = memoryStorage({ [HOLDINGS_DESK_KEY]: "classic" });
saveLabDesk("next", ANALYSIS_DESK, saved);
assertEq(saved.writes.length, 1, "save writes once");
assertEq(saved.writes[0][0], ANALYSIS_DESK.persistKey, "save uses analysis desk key");
assertEq(saved.writes[0][1], "next", "save writes next");
assertEq(loadLabDesk(ANALYSIS_DESK, saved), "next", "load reads saved desk");
assertEq(
  saved.getItem(HOLDINGS_DESK_KEY),
  "classic",
  "saveLabDesk never writes gauntlet.holdings.desk",
);
assertEq(
  saved.writes.some(([key]) => key === HOLDINGS_DESK_KEY),
  false,
  "save write list never includes gauntlet.holdings.desk",
);
assertEq(
  loadLabDesk(ANALYSIS_DESK, memoryStorage({ [ANALYSIS_DESK.persistKey]: "nope" })),
  null,
  "load rejects invalid persist",
);

saveLabDesk("classic", DCA_DESK, saved);
saveLabDesk("next", TAX_DESK, saved);
assertEq(saved.getItem(DCA_DESK.persistKey), "classic", "save writes only dca key");
assertEq(saved.getItem(TAX_DESK.persistKey), "next", "save writes only tax key");
assertEq(
  saved.getItem(HOLDINGS_DESK_KEY),
  "classic",
  "dca/tax saves never write gauntlet.holdings.desk",
);
assertEq(
  saved.writes.every(([key]) => key !== HOLDINGS_DESK_KEY),
  true,
  "no save path writes gauntlet.holdings.desk",
);

const mergedRunway = mergeDeskParam(params("focus=tax_runway"), "classic");
assertEq(mergedRunway.get("focus"), "tax_runway", "merge keeps focus=tax_runway");
assertEq(mergedRunway.get("desk"), "classic", "merge sets desk=classic");

const mergedPrices = mergeDeskParam(params("focus=prices&ticker=AAPL"), "next");
assertEq(mergedPrices.get("focus"), "prices", "merge keeps focus=prices");
assertEq(mergedPrices.get("ticker"), "AAPL", "merge keeps other params");
assertEq(mergedPrices.get("desk"), "next", "merge sets desk=next");

const untouched: LabDesk = "classic";
const source = params("focus=tax_runway");
mergeDeskParam(source, untouched);
assertEq(source.get("desk"), null, "merge does not mutate the source params");
assertEq(source.get("focus"), "tax_runway", "source focus unchanged");

console.log("labDesk.selftest: ok");
