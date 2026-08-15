import { useState, type ReactNode } from "react";

const WIZARD_KEY = "gauntlet.newet.categorize_wizard";

export function wizardDone(): boolean {
  try {
    return localStorage.getItem(WIZARD_KEY) === "1";
  } catch {
    return false;
  }
}

export function markWizardDone(): void {
  try {
    localStorage.setItem(WIZARD_KEY, "1");
  } catch {
    /* ignore */
  }
}

const STEPS = [
  {
    title: "Categories",
    body: "These are the names Grok+ can pick from. Add leaves you need (Moto fuel, a gym, a side business) before any paid matching.",
  },
  {
    title: "Rules",
    body: "Rules used to auto-assign on upload. They now only tag. You can edit them later — skip details for now.",
  },
  {
    title: "Coverage",
    body: "This is how much of the full ledger has a real category. Internals are hidden from spend. Estimates below are leftover Grok+ cost, not a bill.",
  },
  {
    title: "Vendors (free)",
    body: "Assign obvious repeats. Skip anything you don’t recognize — the list will show new shops. Create a category when nothing fits.",
  },
  {
    title: "Grok+ tour",
    body: "One leftover batch (~12 shops). Check misses, add categories, then Approve. Later runs get cheaper for shops you already locked.",
  },
] as const;

export function CategorizeWizard({
  categories,
  rules,
  coverage,
  vendors,
  onStartTour,
  onSkip,
}: {
  categories: ReactNode;
  rules: ReactNode;
  coverage: ReactNode;
  vendors: ReactNode;
  onStartTour: () => void;
  onSkip: () => void;
}) {
  const [step, setStep] = useState(0);
  const meta = STEPS[step];

  function finish(then?: () => void) {
    markWizardDone();
    then?.();
    onSkip();
  }

  return (
    <div className="space-y-4">
      <div className="card space-y-3 border-brand/30 p-4">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-brand">
              Setup {step + 1} / {STEPS.length}
            </p>
            <h2 className="text-lg font-semibold">{meta.title}</h2>
            <p className="mt-1 text-sm text-ink-muted">{meta.body}</p>
          </div>
          <button type="button" className="btn-ghost shrink-0 text-xs" onClick={() => finish()}>
            Skip setup
          </button>
        </div>
        <div className="flex flex-wrap gap-2">
          {step > 0 ? (
            <button type="button" className="btn-ghost text-sm" onClick={() => setStep((s) => s - 1)}>
              Back
            </button>
          ) : null}
          {step < STEPS.length - 1 ? (
            <button type="button" className="btn-primary text-sm" onClick={() => setStep((s) => s + 1)}>
              Next
            </button>
          ) : (
            <button
              type="button"
              className="btn-primary text-sm"
              onClick={() => finish(onStartTour)}
            >
              Start Grok+ tour
            </button>
          )}
          {step === STEPS.length - 1 ? (
            <button type="button" className="btn-secondary text-sm" onClick={() => finish()}>
              Finish without Grok+
            </button>
          ) : null}
        </div>
        <p className="text-[11px] text-ink-faint">
          After this, the full Categorize workspace unlocks. Add missing categories before long
          Grok+ runs so leftover guesses are not wasted.
        </p>
      </div>
      {step === 0 ? categories : null}
      {step === 1 ? rules : null}
      {step === 2 ? coverage : null}
      {step === 3 ? vendors : null}
    </div>
  );
}
