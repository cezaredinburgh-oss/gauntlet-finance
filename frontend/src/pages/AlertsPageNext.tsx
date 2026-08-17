import { useEffect, useMemo, useState } from "react";
import { Info } from "lucide-react";
import { api } from "../api/client";
import type { AlertItem } from "../api/types";
import { ALERTS_DESK } from "../auth/labDesk";
import { EmptyState, PageLoader } from "../components/Spinner";
import { AlertsBoardNext } from "../features/alerts-next/AlertsBoardNext";
import {
  DOMAIN_LABELS,
  groupAlertsByDomain,
  visibleDomains,
  type DomainFilter,
} from "../features/alerts-next/domainBoard";
import { LabNextChrome } from "../lab-chrome/LabNextChrome";
import { cn } from "../lib/cn";
import { markAlertSeen, markAllAlertsSeen } from "../lib/alertSeen";

const LEGEND_TITLE =
  "Danger — act soon · Warn — review · Opportunity — optional edge (DCA, unlock) · Info — context only";

/** Lab next Alerts: typed work items with hrefs. Empty domains collapse. */
export function AlertsPageNext() {
  const [items, setItems] = useState<AlertItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [seenTick, setSeenTick] = useState(0);
  const [reloadTick, setReloadTick] = useState(0);
  const [filter, setFilter] = useState<DomainFilter>("all");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
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
  }, [reloadTick]);

  const grouped = useMemo(() => groupAlertsByDomain(items), [items]);
  const pillDomains = useMemo(() => visibleDomains(grouped, "all"), [grouped]);
  const boardDomains = useMemo(
    () => visibleDomains(grouped, filter),
    [grouped, filter],
  );

  function onAlertActivate(a: AlertItem) {
    markAlertSeen(a);
    setSeenTick((t) => t + 1);
  }

  function onMarkAllSeen() {
    markAllAlertsSeen(items);
    setSeenTick((t) => t + 1);
  }

  return (
    <LabNextChrome config={ALERTS_DESK} label="Alerts desk">
      {loading ? (
        <PageLoader label="Loading alerts…" />
      ) : error ? (
        <EmptyState
          title="Couldn’t load alerts"
          description={error}
          action={
            <button
              type="button"
              className="btn-primary"
              onClick={() => setReloadTick((n) => n + 1)}
            >
              Retry
            </button>
          }
        />
      ) : (
        <>
          <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              <button
                type="button"
                onClick={() => setFilter("all")}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium tabular-nums",
                  filter === "all"
                    ? "bg-brand/15 text-brand ring-1 ring-brand/40"
                    : "bg-white/5 text-ink-muted hover:bg-white/10",
                )}
              >
                All
                <span className="font-bold">{items.length}</span>
              </button>
              {pillDomains.map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setFilter(key)}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium tabular-nums",
                    filter === key
                      ? "bg-brand/15 text-brand ring-1 ring-brand/40"
                      : "bg-white/5 text-ink-muted hover:bg-white/10",
                  )}
                >
                  {DOMAIN_LABELS[key]}
                  <span className="font-bold">{grouped[key].length}</span>
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              {items.length > 0 && (
                <button
                  type="button"
                  className="btn-ghost text-xs"
                  onClick={onMarkAllSeen}
                  title="Clears the unseen badge. Alerts stay listed."
                >
                  Mark all seen
                </button>
              )}
              <button
                type="button"
                className="inline-flex h-6 w-6 items-center justify-center rounded-full text-ink-faint hover:bg-white/5 hover:text-ink-muted"
                title={LEGEND_TITLE}
                aria-label="Alert level legend"
              >
                <Info className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          {items.length === 0 ? (
            <EmptyState
              title="No alerts right now"
              description="You’re within normal spending pace and data looks healthy."
            />
          ) : (
            <AlertsBoardNext
              grouped={grouped}
              domains={boardDomains}
              seenTick={seenTick}
              onActivate={onAlertActivate}
            />
          )}
        </>
      )}
    </LabNextChrome>
  );
}
