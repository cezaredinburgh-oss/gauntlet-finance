/** Shared ROI / health grade ring + chip styles for Investments desk. */

export const GRADE_STYLE: Record<string, string> = {
  A: "bg-ok/20 text-ok ring-ok/40",
  B: "bg-brand/20 text-brand ring-brand/40",
  C: "bg-white/10 text-ink ring-white/20",
  D: "bg-warn/20 text-warn ring-warn/40",
  F: "bg-danger/20 text-danger ring-danger/40",
  "N/A": "bg-white/5 text-ink-faint ring-white/10",
  "—": "bg-white/5 text-ink-faint ring-white/10",
};

/** Soft chip colors by ROI grade (inactive / active). */
export const GRADE_CHIP: Record<string, { idle: string; active: string }> = {
  A: {
    idle: "bg-ok/10 text-ok hover:bg-ok/15",
    active: "bg-ok/25 text-ok ring-1 ring-ok/50",
  },
  B: {
    idle: "bg-brand/10 text-brand hover:bg-brand/15",
    active: "bg-brand/25 text-brand ring-1 ring-brand/50",
  },
  C: {
    idle: "bg-white/8 text-ink-muted hover:bg-white/12 hover:text-ink",
    active: "bg-white/15 text-ink ring-1 ring-white/30",
  },
  D: {
    idle: "bg-warn/10 text-warn hover:bg-warn/15",
    active: "bg-warn/25 text-warn ring-1 ring-warn/50",
  },
  F: {
    idle: "bg-danger/10 text-danger hover:bg-danger/15",
    active: "bg-danger/25 text-danger ring-1 ring-danger/50",
  },
  "—": {
    idle: "bg-white/5 text-ink-faint hover:bg-white/10",
    active: "bg-white/10 text-ink-muted ring-1 ring-white/20",
  },
};

export function gradeStyleClass(grade: string | null | undefined): string {
  const g = grade && grade in GRADE_STYLE ? grade : "—";
  return GRADE_STYLE[g] || GRADE_STYLE["—"];
}
