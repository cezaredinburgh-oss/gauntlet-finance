/**
 * Client-side new-user onboarding progress.
 *
 * v1 is browser-local only (no multi-device sync). Existing installs with a
 * spreadsheet already linked are auto-marked complete so they never see a
 * first-run prompt after deploy.
 */

export const ONBOARDING_STORAGE_KEY = "gauntlet.onboarding.v1";
export const ONBOARDING_VERSION = 1;

export type OnboardingStepId =
  | "welcome"
  | "sheets"
  | "upload"
  | "rules"
  | "ready";

export const ONBOARDING_STEPS: ReadonlyArray<{
  id: OnboardingStepId;
  label: string;
  short: string;
}> = [
  { id: "welcome", label: "Welcome", short: "Welcome" },
  { id: "sheets", label: "Google Sheets", short: "Sheets" },
  { id: "upload", label: "Bank statements", short: "Upload" },
  { id: "rules", label: "Rules & categories", short: "Rules" },
  { id: "ready", label: "You're ready", short: "Ready" },
];

export type OnboardingState = {
  version: number;
  /** User finished the path or was migrated as legacy. */
  completed: boolean;
  /** Soft dismiss of the Home prompt (can still open /onboarding). */
  dismissed: boolean;
  lastStep: OnboardingStepId;
  completedAt?: string;
  dismissedAt?: string;
  /** Set when we auto-complete for pre-existing installs. */
  legacyMigrated?: boolean;
};

function defaultState(): OnboardingState {
  return {
    version: ONBOARDING_VERSION,
    completed: false,
    dismissed: false,
    lastStep: "welcome",
  };
}

export function loadOnboardingState(): OnboardingState {
  try {
    const raw = localStorage.getItem(ONBOARDING_STORAGE_KEY);
    if (!raw) return defaultState();
    const parsed = JSON.parse(raw) as Partial<OnboardingState>;
    return {
      ...defaultState(),
      ...parsed,
      version: ONBOARDING_VERSION,
      lastStep: isStepId(parsed.lastStep) ? parsed.lastStep : "welcome",
      completed: Boolean(parsed.completed),
      dismissed: Boolean(parsed.dismissed),
    };
  } catch {
    return defaultState();
  }
}

export function saveOnboardingState(next: OnboardingState): void {
  try {
    localStorage.setItem(ONBOARDING_STORAGE_KEY, JSON.stringify(next));
  } catch {
    /* private mode */
  }
}

export function isStepId(value: unknown): value is OnboardingStepId {
  return (
    value === "welcome" ||
    value === "sheets" ||
    value === "upload" ||
    value === "rules" ||
    value === "ready"
  );
}

export function stepIndex(id: OnboardingStepId): number {
  return ONBOARDING_STEPS.findIndex((s) => s.id === id);
}

export function markOnboardingStep(step: OnboardingStepId): OnboardingState {
  const cur = loadOnboardingState();
  const next: OnboardingState = { ...cur, lastStep: step };
  saveOnboardingState(next);
  return next;
}

export function markOnboardingComplete(): OnboardingState {
  const next: OnboardingState = {
    ...loadOnboardingState(),
    completed: true,
    dismissed: true,
    lastStep: "ready",
    completedAt: new Date().toISOString(),
  };
  saveOnboardingState(next);
  return next;
}

export function dismissOnboardingPrompt(): OnboardingState {
  const next: OnboardingState = {
    ...loadOnboardingState(),
    dismissed: true,
    dismissedAt: new Date().toISOString(),
  };
  saveOnboardingState(next);
  return next;
}

export function resetOnboardingForPreview(): void {
  /* Preview must not clear real progress — no-op by design. */
}

/**
 * Existing users who already have SPREADSHEET_ID never see a first-run popup.
 * Runs once when no storage key exists and the sheet is already configured.
 */
export function migrateLegacyOnboardingIfNeeded(
  spreadsheetConfigured: boolean | null | undefined,
): OnboardingState {
  const hasKey = (() => {
    try {
      return localStorage.getItem(ONBOARDING_STORAGE_KEY) != null;
    } catch {
      return true;
    }
  })();
  if (hasKey) return loadOnboardingState();
  if (spreadsheetConfigured) {
    const next: OnboardingState = {
      ...defaultState(),
      completed: true,
      dismissed: true,
      lastStep: "ready",
      legacyMigrated: true,
      completedAt: new Date().toISOString(),
    };
    saveOnboardingState(next);
    return next;
  }
  return defaultState();
}

/**
 * Soft Home popup: incomplete + not dismissed + sheet not linked.
 * Never forces a hard gate on the rest of the app.
 */
export function shouldShowSetupPrompt(opts: {
  spreadsheetConfigured: boolean | null | undefined;
  preview?: boolean;
}): boolean {
  if (opts.preview) return false;
  if (opts.spreadsheetConfigured == null) return false;
  const state = migrateLegacyOnboardingIfNeeded(opts.spreadsheetConfigured);
  if (state.completed || state.dismissed) return false;
  return opts.spreadsheetConfigured === false;
}

/** Build path for preview or real onboarding. */
export function onboardingPath(opts?: {
  preview?: boolean;
  step?: OnboardingStepId;
}): string {
  const params = new URLSearchParams();
  if (opts?.preview) params.set("preview", "1");
  if (opts?.step && opts.step !== "welcome") params.set("step", opts.step);
  const q = params.toString();
  return q ? `/onboarding?${q}` : "/onboarding";
}
