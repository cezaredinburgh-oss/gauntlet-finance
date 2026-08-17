/**
 * Self-test for lab-only desk resolution (Analysis/DCA/Tax + Home/Upload/Alerts/Settings + Spending/Categorize).
 * Run: npx --yes tsx src/auth/labDesk.selftest.ts  (from frontend/)
 */
import {
  ALERTS_DESK,
  ANALYSIS_DESK,
  CATEGORIZE_DESK,
  DCA_DESK,
  HOME_DESK,
  SETTINGS_DESK,
  SPENDING_DESK,
  TAX_DESK,
  UPLOAD_DESK,
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

assertEq(HOME_DESK.persistKey, "gauntlet.home.desk", "home persist key");
assertEq(UPLOAD_DESK.persistKey, "gauntlet.upload.desk", "upload persist key");
assertEq(ALERTS_DESK.persistKey, "gauntlet.alerts.desk", "alerts persist key");
assertEq(SETTINGS_DESK.persistKey, "gauntlet.settings.desk", "settings persist key");
assertEq(HOME_DESK.defaultDesk, "next", "home default is next");
assertEq(UPLOAD_DESK.defaultDesk, "next", "upload default is next");
assertEq(ALERTS_DESK.defaultDesk, "next", "alerts default is next");
assertEq(SETTINGS_DESK.defaultDesk, "next", "settings default is next");

for (const [label, user] of [
  ["owner", owner],
  ["sandbox", sandbox],
  ["tour", tour],
  ["null", null],
] as const) {
  const store = memoryStorage();
  const desk = resolveLabDesk(user, params("desk=next"), HOME_DESK, store);
  assertEq(desk, "classic", `${label} must ignore ?desk=next on home`);
  assertEq(store.writes.length, 0, `${label} home resolve must not write storage`);
}

const homeIsolated = memoryStorage({
  [HOLDINGS_DESK_KEY]: "classic",
  [ANALYSIS_DESK.persistKey]: "classic",
  [DCA_DESK.persistKey]: "classic",
  [TAX_DESK.persistKey]: "next",
});
saveLabDesk("next", HOME_DESK, homeIsolated);
assertEq(homeIsolated.writes.length, 1, "home save writes once");
assertEq(homeIsolated.writes[0][0], HOME_DESK.persistKey, "home save uses home desk key");
assertEq(homeIsolated.writes[0][1], "next", "home save writes next");
assertEq(
  homeIsolated.getItem(HOLDINGS_DESK_KEY),
  "classic",
  "saveLabDesk(HOME_DESK) never writes gauntlet.holdings.desk",
);
assertEq(
  homeIsolated.getItem(ANALYSIS_DESK.persistKey),
  "classic",
  "saveLabDesk(HOME_DESK) never writes gauntlet.analysis.desk",
);
assertEq(
  homeIsolated.getItem(DCA_DESK.persistKey),
  "classic",
  "saveLabDesk(HOME_DESK) never writes gauntlet.dca.desk",
);
assertEq(
  homeIsolated.getItem(TAX_DESK.persistKey),
  "next",
  "saveLabDesk(HOME_DESK) never writes gauntlet.tax.desk",
);
assertEq(
  homeIsolated.writes.some(([key]) =>
    key === HOLDINGS_DESK_KEY ||
    key === ANALYSIS_DESK.persistKey ||
    key === DCA_DESK.persistKey ||
    key === TAX_DESK.persistKey,
  ),
  false,
  "home save write list never includes holdings/analysis/dca/tax keys",
);

assertEq(SPENDING_DESK.persistKey, "gauntlet.spending.desk", "spending persist key");
assertEq(CATEGORIZE_DESK.persistKey, "gauntlet.categorize.desk", "categorize persist key");
assertEq(SPENDING_DESK.defaultDesk, "next", "spending default is next");
assertEq(CATEGORIZE_DESK.defaultDesk, "next", "categorize default is next");

for (const [label, user] of [
  ["owner", owner],
  ["sandbox", sandbox],
  ["tour", tour],
  ["null", null],
] as const) {
  for (const [configLabel, config] of [
    ["spending", SPENDING_DESK],
    ["categorize", CATEGORIZE_DESK],
  ] as const) {
    const store = memoryStorage();
    const desk = resolveLabDesk(user, params("desk=next"), config, store);
    assertEq(desk, "classic", `${label} must ignore ?desk=next on ${configLabel}`);
    assertEq(store.writes.length, 0, `${label} ${configLabel} resolve must not write storage`);
  }
}

assertEq(
  resolveLabDesk(lab, params("desk=next"), SPENDING_DESK, memoryStorage()),
  "next",
  "lab + ?desk=next on spending",
);
assertEq(
  resolveLabDesk(lab, params("desk=classic"), SPENDING_DESK, memoryStorage()),
  "classic",
  "lab + ?desk=classic on spending",
);
assertEq(
  resolveLabDesk(lab, params("desk=foo"), SPENDING_DESK, memoryStorage()),
  SPENDING_DESK.defaultDesk,
  "lab + ?desk=foo on spending → default",
);
assertEq(
  resolveLabDesk(lab, params(), SPENDING_DESK, memoryStorage()),
  "next",
  "lab + no query + no persist on spending → next",
);

const spendingPersistClassic = memoryStorage({ [SPENDING_DESK.persistKey]: "classic" });
assertEq(
  resolveLabDesk(lab, params("desk=foo"), SPENDING_DESK, spendingPersistClassic),
  "classic",
  "lab + invalid query uses spending persist",
);
assertEq(spendingPersistClassic.writes.length, 0, "invalid query persist fallback must not write");

const spendingQueryBeats = memoryStorage({ [SPENDING_DESK.persistKey]: "classic" });
assertEq(
  resolveLabDesk(lab, params("desk=next"), SPENDING_DESK, spendingQueryBeats),
  "next",
  "lab spending query beats persist",
);
assertEq(spendingQueryBeats.writes.length, 0, "spending query path must not persist");

assertEq(
  resolveLabDesk(lab, params("desk=next"), CATEGORIZE_DESK, memoryStorage()),
  "next",
  "lab + ?desk=next on categorize",
);
assertEq(
  resolveLabDesk(lab, params("desk=classic"), CATEGORIZE_DESK, memoryStorage()),
  "classic",
  "lab + ?desk=classic on categorize",
);
assertEq(
  resolveLabDesk(lab, params("desk=foo"), CATEGORIZE_DESK, memoryStorage()),
  CATEGORIZE_DESK.defaultDesk,
  "lab + ?desk=foo on categorize → default",
);
assertEq(
  resolveLabDesk(lab, params(), CATEGORIZE_DESK, memoryStorage()),
  "next",
  "lab + no query + no persist on categorize → next",
);

const categorizePersistClassic = memoryStorage({ [CATEGORIZE_DESK.persistKey]: "classic" });
assertEq(
  resolveLabDesk(lab, params("desk=foo"), CATEGORIZE_DESK, categorizePersistClassic),
  "classic",
  "lab + invalid query uses categorize persist",
);
assertEq(categorizePersistClassic.writes.length, 0, "categorize invalid query persist fallback must not write");

const categorizeQueryBeats = memoryStorage({ [CATEGORIZE_DESK.persistKey]: "classic" });
assertEq(
  resolveLabDesk(lab, params("desk=next"), CATEGORIZE_DESK, categorizeQueryBeats),
  "next",
  "lab categorize query beats persist",
);
assertEq(categorizeQueryBeats.writes.length, 0, "categorize query path must not persist");

const spendingResolveProbe = memoryStorage({
  [HOLDINGS_DESK_KEY]: "classic",
  [SPENDING_DESK.persistKey]: "classic",
  [CATEGORIZE_DESK.persistKey]: "classic",
});
resolveLabDesk(lab, params("desk=next"), SPENDING_DESK, spendingResolveProbe);
resolveLabDesk(lab, params(), SPENDING_DESK, spendingResolveProbe);
resolveLabDesk(owner, params("desk=next"), SPENDING_DESK, spendingResolveProbe);
resolveLabDesk(lab, params("desk=next"), CATEGORIZE_DESK, spendingResolveProbe);
resolveLabDesk(lab, params(), CATEGORIZE_DESK, spendingResolveProbe);
resolveLabDesk(owner, params("desk=next"), CATEGORIZE_DESK, spendingResolveProbe);
assertEq(spendingResolveProbe.writes.length, 0, "spending/categorize resolve writes zero storage");

const expenseIsolated = memoryStorage({
  [HOLDINGS_DESK_KEY]: "classic",
  [ANALYSIS_DESK.persistKey]: "classic",
  [DCA_DESK.persistKey]: "classic",
  [TAX_DESK.persistKey]: "next",
  [UPLOAD_DESK.persistKey]: "classic",
  [ALERTS_DESK.persistKey]: "classic",
  [SETTINGS_DESK.persistKey]: "classic",
  [HOME_DESK.persistKey]: "classic",
  [CATEGORIZE_DESK.persistKey]: "classic",
});
saveLabDesk("next", SPENDING_DESK, expenseIsolated);
assertEq(expenseIsolated.writes.length, 1, "spending save writes once");
assertEq(expenseIsolated.writes[0][0], SPENDING_DESK.persistKey, "spending save uses spending desk key");
assertEq(expenseIsolated.writes[0][1], "next", "spending save writes next");
assertEq(loadLabDesk(SPENDING_DESK, expenseIsolated), "next", "load reads saved spending desk");
assertEq(
  expenseIsolated.getItem(CATEGORIZE_DESK.persistKey),
  "classic",
  "saveLabDesk(SPENDING_DESK) does not write gauntlet.categorize.desk",
);

saveLabDesk("next", CATEGORIZE_DESK, expenseIsolated);
assertEq(expenseIsolated.writes.length, 2, "categorize save writes once more");
assertEq(expenseIsolated.writes[1][0], CATEGORIZE_DESK.persistKey, "categorize save uses categorize desk key");
assertEq(expenseIsolated.writes[1][1], "next", "categorize save writes next");
assertEq(loadLabDesk(CATEGORIZE_DESK, expenseIsolated), "next", "load reads saved categorize desk");
assertEq(
  expenseIsolated.getItem(SPENDING_DESK.persistKey),
  "next",
  "saveLabDesk(CATEGORIZE_DESK) does not overwrite gauntlet.spending.desk",
);

assertEq(
  expenseIsolated.getItem(HOLDINGS_DESK_KEY),
  "classic",
  "spending/categorize saves never write gauntlet.holdings.desk",
);
assertEq(
  expenseIsolated.getItem(ANALYSIS_DESK.persistKey),
  "classic",
  "spending/categorize saves never write gauntlet.analysis.desk",
);
assertEq(
  expenseIsolated.getItem(DCA_DESK.persistKey),
  "classic",
  "spending/categorize saves never write gauntlet.dca.desk",
);
assertEq(
  expenseIsolated.getItem(TAX_DESK.persistKey),
  "next",
  "spending/categorize saves never write gauntlet.tax.desk",
);
assertEq(
  expenseIsolated.getItem(UPLOAD_DESK.persistKey),
  "classic",
  "spending/categorize saves never write gauntlet.upload.desk",
);
assertEq(
  expenseIsolated.getItem(ALERTS_DESK.persistKey),
  "classic",
  "spending/categorize saves never write gauntlet.alerts.desk",
);
assertEq(
  expenseIsolated.getItem(SETTINGS_DESK.persistKey),
  "classic",
  "spending/categorize saves never write gauntlet.settings.desk",
);
assertEq(
  expenseIsolated.getItem(HOME_DESK.persistKey),
  "classic",
  "spending/categorize saves never write gauntlet.home.desk",
);
assertEq(
  expenseIsolated.writes.every(
    ([key]) => key === SPENDING_DESK.persistKey || key === CATEGORIZE_DESK.persistKey,
  ),
  true,
  "spending/categorize save write list only includes those keys",
);

const categorizeOnly = memoryStorage({
  [SPENDING_DESK.persistKey]: "classic",
});
saveLabDesk("next", CATEGORIZE_DESK, categorizeOnly);
assertEq(categorizeOnly.writes.length, 1, "categorize-only save writes once");
assertEq(categorizeOnly.writes[0][0], CATEGORIZE_DESK.persistKey, "categorize-only save uses categorize key");
assertEq(
  categorizeOnly.getItem(SPENDING_DESK.persistKey),
  "classic",
  "saveLabDesk(CATEGORIZE_DESK) does not write gauntlet.spending.desk",
);

const mergedExpense = mergeDeskParam(
  params("mode=rules&panel=grokplus&category_id=cat-1&date_from=2024-01-01&date_to=2024-12-31&hide_transfers=1"),
  "next",
);
assertEq(mergedExpense.get("mode"), "rules", "merge keeps mode=rules");
assertEq(mergedExpense.get("panel"), "grokplus", "merge keeps panel=grokplus");
assertEq(mergedExpense.get("category_id"), "cat-1", "merge keeps category_id");
assertEq(mergedExpense.get("date_from"), "2024-01-01", "merge keeps date_from");
assertEq(mergedExpense.get("date_to"), "2024-12-31", "merge keeps date_to");
assertEq(mergedExpense.get("hide_transfers"), "1", "merge keeps hide_transfers");
assertEq(mergedExpense.get("desk"), "next", "merge sets desk=next");

const expenseSource = params(
  "mode=rules&panel=grokplus&category_id=cat-1&date_from=2024-01-01&date_to=2024-12-31&hide_transfers=1",
);
mergeDeskParam(expenseSource, "classic");
assertEq(expenseSource.get("desk"), null, "merge does not mutate the source URLSearchParams");
assertEq(expenseSource.get("mode"), "rules", "source mode unchanged");
assertEq(expenseSource.get("panel"), "grokplus", "source panel unchanged");
assertEq(expenseSource.get("category_id"), "cat-1", "source category_id unchanged");
assertEq(expenseSource.get("date_from"), "2024-01-01", "source date_from unchanged");
assertEq(expenseSource.get("date_to"), "2024-12-31", "source date_to unchanged");
assertEq(expenseSource.get("hide_transfers"), "1", "source hide_transfers unchanged");

console.log("labDesk.selftest: ok");
