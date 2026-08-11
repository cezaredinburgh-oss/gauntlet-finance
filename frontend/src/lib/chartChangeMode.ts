/** Persist Performance | Book primary metric for MV charts. */

export type ChartChangeMode = "performance" | "book";

export const CHART_CHANGE_MODE_KEY = "gauntlet.chart.changeMode";

export function loadChartChangeMode(): ChartChangeMode {
  try {
    const raw = localStorage.getItem(CHART_CHANGE_MODE_KEY);
    if (raw === "book" || raw === "performance") return raw;
  } catch {
    /* private mode */
  }
  return "performance";
}

export function saveChartChangeMode(mode: ChartChangeMode): void {
  try {
    localStorage.setItem(CHART_CHANGE_MODE_KEY, mode);
  } catch {
    /* ignore */
  }
}
