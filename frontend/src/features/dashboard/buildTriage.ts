import type { AlertItem, PortfolioSnapshot } from "../../api/types";

export type TriageLevel = "danger" | "warn" | "info";

export type TriageItem = {
  id: string;
  level: TriageLevel;
  title: string;
  body?: string;
  href: string;
};

/**
 * Ranked ops list for Home: alerts + high/med health issues + uncategorized spend.
 * Max items applied by caller.
 */
export function buildTriageItems(opts: {
  alerts: AlertItem[];
  health: PortfolioSnapshot["health"] | null | undefined;
  uncategorizedPct: number;
}): TriageItem[] {
  const out: TriageItem[] = [];
  const seen = new Set<string>();

  const push = (item: TriageItem) => {
    const key = `${item.level}:${item.title}`;
    if (seen.has(key)) return;
    seen.add(key);
    out.push(item);
  };

  for (const a of opts.alerts) {
    if (a.level !== "danger" && a.level !== "warn") continue;
    push({
      id: `alert-${a.id}`,
      level: a.level,
      title: a.title,
      body: a.body,
      href: a.href || "/alerts",
    });
  }

  for (const iss of opts.health?.issues || []) {
    if (iss.severity !== "high" && iss.severity !== "medium") continue;
    push({
      id: `health-${iss.title}`,
      level: iss.severity === "high" ? "danger" : "warn",
      title: iss.title,
      body: iss.detail,
      href: "/investments",
    });
  }

  if (opts.uncategorizedPct >= 20) {
    push({
      id: "uncat-spend",
      level: "warn",
      title: `${opts.uncategorizedPct.toFixed(0)}% of period spend uncategorized`,
      body: "Rules and merchant map improve cash accuracy.",
      href: "/expenses/categorize",
    });
  }

  const rank = (l: TriageLevel) => (l === "danger" ? 0 : l === "warn" ? 1 : 2);
  out.sort((a, b) => rank(a.level) - rank(b.level));
  return out;
}
