import { useState } from "react";
import { Sparkles, Store, Tags } from "lucide-react";

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

export function CategorizeWizard({
  onOpenVendors,
  onOpenCategories,
  onStartTour,
  onSkip,
}: {
  onOpenVendors: () => void;
  onOpenCategories: () => void;
  onStartTour: () => void;
  onSkip: () => void;
}) {
  const [step, setStep] = useState(0);

  function finish(then?: () => void) {
    markWizardDone();
    then?.();
    onSkip();
  }

  const cards = [
    {
      icon: Tags,
      title: "1 · Categories",
      body: "Check the category list for leaves you need (Moto fuel, a gym, a side business). Grok+ can only propose names that exist.",
      primary: "Review categories",
      onPrimary: () => {
        onOpenCategories();
        setStep(1);
      },
    },
    {
      icon: Store,
      title: "2 · Vendors (free)",
      body: "Open By vendor and assign obvious repeats. Create a category when a shop doesn’t fit. This teaches memory and costs nothing.",
      primary: "Open vendor list",
      onPrimary: () => {
        onOpenVendors();
        setStep(2);
      },
    },
    {
      icon: Sparkles,
      title: "3 · Short Grok+ tour",
      body: "The first Grok+ run is one leftover batch (~12 shops) so you can check misses before spending more.",
      primary: "Start Grok+ tour",
      onPrimary: () => finish(onStartTour),
    },
  ];

  const card = cards[Math.min(step, cards.length - 1)];
  const Icon = card.icon;

  return (
    <div className="card space-y-3 border-brand/30 p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-brand">
            Categorize setup · {step + 1} / 3
          </p>
          <h2 className="text-lg font-semibold">{card.title}</h2>
          <p className="mt-1 text-sm text-ink-muted">{card.body}</p>
        </div>
        <button
          type="button"
          className="btn-ghost shrink-0 text-xs"
          onClick={() =>
            finish(() => {
              /* stay on review */
            })
          }
        >
          Skip setup
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn-primary text-sm" onClick={card.onPrimary}>
          <Icon className="h-4 w-4" />
          {card.primary}
        </button>
        {step < 2 ? (
          <button type="button" className="btn-secondary text-sm" onClick={() => setStep((s) => s + 1)}>
            Next
          </button>
        ) : null}
      </div>
      <p className="text-[11px] text-ink-faint">
        Power users: skip anytime. Before Grok+, still add missing categories so leftover guesses
        are not wasted.
      </p>
    </div>
  );
}
