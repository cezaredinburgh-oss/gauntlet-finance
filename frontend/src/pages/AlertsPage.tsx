import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Info, Lightbulb, ShieldAlert } from "lucide-react";
import { api } from "../api/client";
import type { AlertItem } from "../api/types";
import { EmptyState, PageLoader } from "../components/Spinner";
import { cn } from "../lib/cn";
import { summarizeAlertBuckets } from "../features/dashboard/alertBuckets";

type DomainKey = "spending" | "stocks" | "crypto";

const DOMAIN_META: Record<
  DomainKey,
  { label: string; accent: string; border: string }
> = {
  spending: {
    label: "Spending",
    accent: "text-brand",
    border: "border-brand/30",
  },
  stocks: {
    label: "Stocks",
    accent: "text-ok",
    border: "border-ok/30",
  },
  crypto: {
    label: "Crypto",
    accent: "text-warn",
    border: "border-warn/30",
  },
};

function levelStyle(level: string): string {
  switch (level) {
    case "danger":
      return "bg-danger/20 text-danger";
    case "warn":
      return "bg-warn/20 text-warn";
    case "opportunity":
      return "bg-ok/20 text-ok";
    default:
      return "bg-white/10 text-ink-muted";
  }
}

function LevelIcon({ level }: { level: string }) {
  if (level === "danger") return <ShieldAlert className="h-4 w-4" />;
  if (level === "warn") return <AlertTriangle className="h-4 w-4" />;
  if (level === "opportunity") return <Lightbulb className="h-4 w-4" />;
  return <Info className="h-4 w-4" />;
}

export function AlertsPage() {
  const [items, setItems] = useState<AlertItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const r = await api.alerts();
        if (!cancelled) setItems(r.items);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const byDomain = useMemo(() => {
    const map: Record<DomainKey, AlertItem[]> = {
      spending: [],
      stocks: [],
      crypto: [],
    };
    const counts = summarizeAlertBuckets(items);
    void counts;
    for (const a of items) {
      const d = summarizeAlertBuckets([a]);
      if (d.crypto) map.crypto.push(a);
      else if (d.stocks) map.stocks.push(a);
      else map.spending.push(a);
    }
    // Sort: danger, warn, opportunity, info
    const rank = (l: string) =>
      l === "danger" ? 0 : l === "warn" ? 1 : l === "opportunity" ? 2 : 3;
    for (const k of Object.keys(map) as DomainKey[]) {
      map[k].sort((a, b) => rank(String(a.level)) - rank(String(b.level)));
    }
    return map;
  }, [items]);

  const totals = useMemo(() => summarizeAlertBuckets(items), [items]);

  if (loading) return <PageLoader label="Loading alerts…" />;
  if (error) {
    return <EmptyState title="Couldn’t load alerts" description={error} />;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Alerts</h1>
        <p className="text-sm text-ink-muted">
          Spend pace, data quality, tax unlocks, and DCA opportunities — grouped by
          domain. Opportunity is separate from warnings.
        </p>
      </div>

      <section
        className="relative overflow-hidden rounded-2xl border p-5 sm:p-6"
        style={{
          background:
            "linear-gradient(135deg, rgba(59,130,246,0.14), rgba(16,185,129,0.08) 50%, rgba(15,23,42,0.9))",
          borderColor: "rgba(52,211,153,0.3)",
          boxShadow: "0 16px 40px rgba(0,0,0,0.3)",
        }}
      >
        <div className="relative mb-4 flex flex-wrap items-end justify-between gap-2">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-muted">
              Alert desk
            </div>
            <p className="mt-0.5 text-xs text-ink-faint">
              {totals.total === 0
                ? "No open alerts"
                : `${totals.total} alert${totals.total === 1 ? "" : "s"} · ${totals.spending} spend · ${totals.stocks} stocks · ${totals.crypto} crypto`}
            </p>
          </div>
        </div>

        {items.length === 0 ? (
          <EmptyState
            title="No alerts right now"
            description="You’re within normal spending pace and data looks healthy."
          />
        ) : (
          <div className="relative grid gap-4 lg:grid-cols-3">
            {(["spending", "stocks", "crypto"] as DomainKey[]).map((key) => {
              const meta = DOMAIN_META[key];
              const list = byDomain[key];
              return (
                <div
                  key={key}
                  className={cn(
                    "flex min-h-[12rem] flex-col rounded-xl border bg-black/25 p-4",
                    meta.border,
                  )}
                >
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <h2 className={cn("text-sm font-semibold tracking-wide", meta.accent)}>
                      {meta.label}
                    </h2>
                    <span className="badge bg-white/5 text-ink-muted tabular-nums">
                      {list.length}
                    </span>
                  </div>
                  {list.length === 0 ? (
                    <p className="text-xs text-ink-faint">No alerts in this domain.</p>
                  ) : (
                    <ul className="space-y-2">
                      {list.map((a) => (
                        <li
                          key={a.id}
                          className="rounded-lg border border-white/10 bg-white/[0.03] p-3"
                        >
                          <div className="flex gap-2">
                            <span
                              className={cn(
                                "mt-0.5 shrink-0 rounded-md p-1.5",
                                levelStyle(String(a.level)),
                              )}
                            >
                              <LevelIcon level={String(a.level)} />
                            </span>
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-1.5">
                                <span className="text-sm font-semibold text-ink">
                                  {a.title}
                                </span>
                                <span
                                  className={cn(
                                    "rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase",
                                    levelStyle(String(a.level)),
                                  )}
                                >
                                  {a.level}
                                </span>
                              </div>
                              <p className="mt-1 text-xs text-ink-muted">{a.body}</p>
                              {a.href && (
                                <Link
                                  to={a.href}
                                  className="mt-1.5 inline-block text-[11px] font-medium text-brand hover:underline"
                                >
                                  Open related page →
                                </Link>
                              )}
                            </div>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
