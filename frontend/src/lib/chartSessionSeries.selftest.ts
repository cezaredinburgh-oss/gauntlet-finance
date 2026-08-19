/**
 * Self-test for 1D RTH Area vs extended dashed Line split.
 * Run: npx --yes tsx src/lib/chartSessionSeries.selftest.ts  (from frontend/)
 */
import { rthValuesOf, splitSessionSeries } from "./chartSessionSeries";

function assert(cond: unknown, msg: string): asserts cond {
  if (!cond) throw new Error(msg);
}

const prior = "2026-08-07T19:55:00.000Z"; // 15:55 ET
const pre = "2026-08-10T08:30:00.000Z"; // 04:30 ET
const rthOpen = "2026-08-10T13:30:00.000Z"; // 09:30 ET
const rthMid = "2026-08-10T14:00:00.000Z"; // 10:00 ET
const rthLast = "2026-08-10T19:55:00.000Z"; // 15:55 ET
const ahOpen = "2026-08-10T20:00:00.000Z"; // 16:00 ET
const ahLate = "2026-08-10T21:00:00.000Z"; // 17:00 ET

const tape = [
  { date: prior, value: "100", session: "prior_close" as const },
  { date: pre, value: "101", session: "pre" as const },
  { date: rthOpen, value: "102", session: "rth" as const },
  { date: rthMid, value: "102.5", session: "rth" as const },
  { date: rthLast, value: "103", session: "rth" as const },
  { date: ahOpen, value: "104", session: "ah" as const },
  { date: ahLate, value: "105", session: "ah" as const },
];

const split = splitSessionSeries(tape);
const byDate = Object.fromEntries(split.map((r) => [r.date, r]));

assert(byDate[prior].rthValue == null, "seed is not rthValue");
assert(byDate[prior].extValue === 100, "seed is extValue");
assert(byDate[pre].rthValue == null, "04:30 pre is dashed");
assert(byDate[pre].extValue === 101, "04:30 pre extValue");
assert(byDate[rthMid].rthValue === 102.5, "10:00 rth Area");
assert(byDate[rthMid].extValue == null, "interior RTH is not dashed");
assert(byDate[rthOpen].rthValue === 102, "first RTH in Area");
assert(byDate[rthOpen].extValue === 102, "first RTH join copy on dashed");
assert(byDate[rthLast].rthValue === 103, "15:55 last RTH Area");
assert(byDate[rthLast].extValue === 103, "15:55 join copy so AH continues");
assert(byDate[ahOpen].rthValue == null, "16:00 is AH not Area");
assert(byDate[ahOpen].extValue === 104, "16:00 dashed");
assert(byDate[ahLate].rthValue == null, "17:00 is AH");
assert(byDate[ahLate].extValue === 105, "17:00 dashed");

const rthYs = rthValuesOf(split);
assert(rthYs.length === 3, `RTH y count ${rthYs.length}`);
assert(!rthYs.includes(100), "seed y not in RTH span");
assert(!rthYs.includes(101), "pre y not in RTH span");
assert(!rthYs.includes(104), "AH y not in RTH span");

const crypto = splitSessionSeries([
  { date: "2026-08-09T22:00:00.000Z", value: "80", session: "local" },
  { date: "2026-08-10T12:00:00.000Z", value: "82", session: "local" },
]);
assert(crypto[0].rthValue === 80, "crypto passthrough solid");
assert(crypto[0].extValue == null, "crypto has no dashed ext");
assert(crypto[1].rthValue === 82, "crypto last solid");

const untagged = splitSessionSeries([
  { date: "2026-01-01", value: "10" },
  { date: "2026-01-02", value: "11" },
]);
assert(untagged[0].rthValue === 10, "daily untagged is Area");
assert(untagged[0].extValue == null, "daily untagged not dashed");

console.log("chartSessionSeries.selftest: ok");
