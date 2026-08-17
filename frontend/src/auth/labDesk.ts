import type { AuthMe } from "../api/types";
import { isLabSession } from "./isLabSession";

export type LabDesk = "classic" | "next";

export type DeskStorage = Pick<Storage, "getItem" | "setItem">;

export type LabDeskConfig = {
  persistKey: string;
  defaultDesk: LabDesk;
};

export const ANALYSIS_DESK: LabDeskConfig = {
  persistKey: "gauntlet.analysis.desk",
  defaultDesk: "next",
};

export const DCA_DESK: LabDeskConfig = {
  persistKey: "gauntlet.dca.desk",
  defaultDesk: "next",
};

export const TAX_DESK: LabDeskConfig = {
  persistKey: "gauntlet.tax.desk",
  defaultDesk: "next",
};

export const HOME_DESK: LabDeskConfig = {
  persistKey: "gauntlet.home.desk",
  defaultDesk: "next",
};

export const UPLOAD_DESK: LabDeskConfig = {
  persistKey: "gauntlet.upload.desk",
  defaultDesk: "next",
};

export const ALERTS_DESK: LabDeskConfig = {
  persistKey: "gauntlet.alerts.desk",
  defaultDesk: "next",
};

export const SETTINGS_DESK: LabDeskConfig = {
  persistKey: "gauntlet.settings.desk",
  defaultDesk: "next",
};

export function loadLabDesk(
  config: LabDeskConfig,
  storage: DeskStorage = window.localStorage,
): LabDesk | null {
  try {
    const raw = storage.getItem(config.persistKey);
    if (raw === "classic" || raw === "next") return raw;
  } catch {
    /* ignore */
  }
  return null;
}

export function saveLabDesk(
  desk: LabDesk,
  config: LabDeskConfig,
  storage: DeskStorage = window.localStorage,
): void {
  try {
    storage.setItem(config.persistKey, desk);
  } catch {
    /* ignore */
  }
}

/** Lab-only. Query wins; persist is read-only here (no writes). */
export function resolveLabDesk(
  user: Pick<AuthMe, "is_demo" | "demo_kind"> | null | undefined,
  searchParams: URLSearchParams,
  config: LabDeskConfig,
  storage: DeskStorage = window.localStorage,
): LabDesk {
  if (!isLabSession(user)) return "classic";
  const q = searchParams.get("desk");
  if (q === "classic" || q === "next") return q;
  const stored = loadLabDesk(config, storage);
  if (stored === "classic" || stored === "next") return stored;
  return config.defaultDesk;
}

/** Merge `desk` into the current query; keep focus and other params. */
export function mergeDeskParam(
  currentSearchParams: URLSearchParams,
  desk: LabDesk,
): URLSearchParams {
  const next = new URLSearchParams(currentSearchParams);
  next.set("desk", desk);
  return next;
}
