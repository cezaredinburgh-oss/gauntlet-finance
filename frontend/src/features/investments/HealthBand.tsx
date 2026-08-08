import type { PortfolioSnapshot } from "../../api/types";
import { cn } from "../../lib/cn";

const GRADE_STYLE: Record<string, string> = {
  A: "bg-ok/20 text-ok ring-ok/40",
  B: "bg-brand/20 text-brand ring-brand/40",
  C: "bg-white/10 text-ink ring-white/20",
  D: "bg-warn/20 text-warn ring-warn/40",
  F: "bg-danger/20 text-danger ring-danger/40",
  "—": "bg-white/5 text-ink-faint ring-white/10",
};

export function HealthBand({
  health,
}: {
  health: NonNullable<PortfolioSnapshot["health"]>;
}) {
  const grade = health.grade in GRADE_STYLE ? health.grade : "—";
  const c = health.concentration;
  const focus = (health.issues || [])
    .filter((i) => i.severity === "high" || i.severity === "medium")
    .slice(0, 3);
  const goods = (health.issues || []).filter((i) => i.severity === "good").slice(0, 2);
  const show = focus.length ? focus : goods;

  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-start gap-4">
        <div
          className={cn(
            "flex h-16 w-16 shrink-0 flex-col items-center justify-center rounded-2xl ring-1",
            GRADE_STYLE[grade] || GRADE_STYLE["—"],
          )}
        >
          <span className="text-2xl font-bold leading-none">{health.grade}</span>
          <span className="text-[10px] opacity-80">{health.score}/100</span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">Portfolio health</div>
          <p className="mt-0.5 text-sm text-ink-muted">{health.summary}</p>
          <p className="mt-2 text-xs text-ink-faint">
            {c.largest_position_line}
            {" · "}
            Top3 {c.top3_weight_pct.toFixed(0)}%
            {" · "}
            Crypto {c.crypto_weight_pct.toFixed(0)}%
            {" · "}
            Tax-free basis {c.tax_free_basis_pct.toFixed(0)}%
          </p>
        </div>
      </div>
      {show.length > 0 && (
        <ul className="mt-4 space-y-2 border-t border-white/5 pt-3">
          {show.map((iss) => (
            <li key={iss.title} className="text-xs">
              <span
                className={cn(
                  "mr-2 inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase",
                  iss.severity === "high" && "bg-danger/20 text-danger",
                  iss.severity === "medium" && "bg-warn/20 text-warn",
                  iss.severity === "good" && "bg-ok/15 text-ok",
                  iss.severity === "low" && "bg-white/10 text-ink-muted",
                )}
              >
                {iss.severity}
              </span>
              <span className="font-medium text-ink">{iss.title}</span>
              <span className="mt-0.5 block text-ink-faint">{iss.detail}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

