import { Link } from "react-router-dom";
import { AlertTriangle, Info, Lightbulb, ShieldAlert } from "lucide-react";
import type { AlertItem } from "../../api/types";
import { cn } from "../../lib/cn";
import { isAlertSeen } from "../../lib/alertSeen";

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

export function AlertCardNext({
  alert: a,
  seenTick,
  onActivate,
}: {
  alert: AlertItem;
  seenTick: number;
  onActivate: (a: AlertItem) => void;
}) {
  void seenTick;
  const seen = isAlertSeen(a);
  const href = a.href || undefined;

  return (
    <li
      className={cn(
        "min-w-0 rounded-lg border border-white/10 bg-white/[0.03] transition hover:border-white/20",
        seen && "opacity-55",
      )}
    >
      {/*
        Mark-seen button and Open Link are siblings —
        do not nest a button inside the Link (a11y).
      */}
      <button
        type="button"
        onClick={() => onActivate(a)}
        className={cn(
          "w-full min-w-0 p-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40 focus-visible:ring-inset",
          href ? "rounded-t-lg" : "rounded-lg",
        )}
      >
        <div className="flex min-w-0 gap-2">
          <span
            className={cn(
              "mt-0.5 shrink-0 rounded-md p-1.5",
              levelStyle(String(a.level)),
            )}
          >
            <LevelIcon level={String(a.level)} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="min-w-0 text-pretty break-words text-sm font-semibold text-ink">
              {a.title}
            </p>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <span
                className={cn(
                  "rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase",
                  levelStyle(String(a.level)),
                )}
              >
                {a.level}
              </span>
              {seen && (
                <span className="text-[10px] font-medium uppercase text-ink-faint">
                  Seen
                </span>
              )}
            </div>
            <p className="mt-1 min-w-0 break-words text-xs text-ink-muted">{a.body}</p>
          </div>
        </div>
      </button>
      {href ? (
        <div className="border-t border-white/5 px-3 py-2">
          <Link
            to={href}
            onClick={() => onActivate(a)}
            className="inline-flex w-full min-w-0 items-center justify-end text-[11px] font-semibold text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40"
          >
            Open →
          </Link>
        </div>
      ) : null}
    </li>
  );
}
