import { Link } from "react-router-dom";
import { AlertTriangle, ArrowRight, Info, ShieldAlert } from "lucide-react";
import { cn } from "../../lib/cn";
import type { TriageItem } from "./buildTriage";

export function TriageList({ items, max = 5 }: { items: TriageItem[]; max?: number }) {
  const show = items.slice(0, max);
  if (show.length === 0) return null;

  return (
    <section className="card p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold tracking-wide text-warn">Needs attention</h2>
        <Link
          to="/expenses/alerts"
          className="inline-flex items-center gap-0.5 text-xs font-medium text-brand hover:underline"
        >
          All alerts <ArrowRight className="h-3 w-3" />
        </Link>
      </div>
      <ul className="space-y-2">
        {show.map((a) => (
          <li key={a.id}>
            <Link
              to={a.href}
              className={cn(
                "flex gap-2 rounded-lg border px-3 py-2 text-sm transition hover:border-brand/40",
                a.level === "danger"
                  ? "border-danger/30 bg-danger/5"
                  : a.level === "warn"
                    ? "border-warn/30 bg-warn/5"
                    : "border-white/10 bg-black/15",
              )}
            >
              {a.level === "danger" ? (
                <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
              ) : a.level === "warn" ? (
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
              ) : (
                <Info className="mt-0.5 h-4 w-4 shrink-0 text-ink-muted" />
              )}
              <div className="min-w-0">
                <div className="font-medium text-ink">{a.title}</div>
                {a.body && (
                  <div className="truncate text-xs text-ink-muted">{a.body}</div>
                )}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
