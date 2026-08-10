import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Info, ShieldAlert } from "lucide-react";
import { api } from "../api/client";
import type { AlertItem } from "../api/types";
import { EmptyState, PageLoader } from "../components/Spinner";

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

  if (loading) return <PageLoader label="Loading alerts…" />;
  if (error) {
    return <EmptyState title="Couldn’t load alerts" description={error} />;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Alerts</h1>
        <p className="text-sm text-ink-muted">
          Spend pace, categorization gaps, tax unlocks, DCA opportunities on holdings,
          prices, and data-quality notes
        </p>
      </div>

      {items.length === 0 ? (
        <EmptyState
          title="No alerts right now"
          description="You’re within normal spending pace and data looks healthy."
        />
      ) : (
        <ul className="space-y-3">
          {items.map((a) => (
            <li
              key={a.id}
              className={`card flex gap-3 p-4 ${
                a.level === "warn"
                  ? "border-warn/30"
                  : a.level === "danger"
                    ? "border-danger/30"
                    : "border-white/5"
              }`}
            >
              <span
                className={`mt-0.5 shrink-0 rounded-lg p-2 ${
                  a.level === "warn"
                    ? "bg-warn/15 text-warn"
                    : a.level === "danger"
                      ? "bg-danger/15 text-danger"
                      : "bg-white/5 text-ink-muted"
                }`}
              >
                {a.level === "warn" ? (
                  <AlertTriangle className="h-4 w-4" />
                ) : a.level === "danger" ? (
                  <ShieldAlert className="h-4 w-4" />
                ) : (
                  <Info className="h-4 w-4" />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="font-semibold">{a.title}</div>
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                      a.level === "danger"
                        ? "bg-danger/20 text-danger"
                        : a.level === "warn"
                          ? "bg-warn/20 text-warn"
                          : "bg-white/10 text-ink-muted"
                    }`}
                  >
                    {a.level}
                  </span>
                </div>
                <p className="mt-1 text-sm text-ink-muted">{a.body}</p>
                {a.href && (
                  <Link
                    to={a.href}
                    className="mt-2 inline-block text-xs font-medium text-brand hover:underline"
                  >
                    Open related page →
                  </Link>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
