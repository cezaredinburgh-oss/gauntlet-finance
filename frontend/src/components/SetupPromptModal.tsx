import { Link } from "react-router-dom";
import { ArrowRight, Sparkles, X } from "lucide-react";
import { onboardingPath } from "../lib/onboarding";
import { cn } from "../lib/cn";

type Props = {
  open: boolean;
  onDismiss: () => void;
  onContinue: () => void;
};

/**
 * Soft, high-visibility prompt for incomplete first-run setup.
 * Does not block the rest of the app — user can dismiss or continue later.
 */
export function SetupPromptModal({ open, onDismiss, onContinue }: Props) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[80] flex items-end justify-center p-4 sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="setup-prompt-title"
    >
      <button
        type="button"
        className="absolute inset-0 bg-slate-950/70 backdrop-blur-sm"
        aria-label="Dismiss setup prompt backdrop"
        onClick={onDismiss}
      />
      <div
        className={cn(
          "relative z-[81] w-full max-w-lg overflow-hidden rounded-2xl border border-brand/40",
          "bg-slate-950/95 shadow-2xl shadow-brand/10",
        )}
      >
        <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-brand via-emerald-400 to-brand" />
        <div className="flex items-start justify-between gap-3 px-5 pt-5">
          <div className="flex items-center gap-2 text-brand">
            <Sparkles className="h-5 w-5 shrink-0" />
            <span className="text-xs font-semibold uppercase tracking-wide">
              Finish setup
            </span>
          </div>
          <button
            type="button"
            className="rounded-lg p-1.5 text-ink-muted hover:bg-white/5 hover:text-ink"
            aria-label="Dismiss"
            onClick={onDismiss}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-3 px-5 pb-2 pt-3">
          <h2 id="setup-prompt-title" className="text-lg font-semibold tracking-tight">
            Complete your Gauntlet setup
          </h2>
          <p className="text-sm text-ink-muted">
            A few guided steps and you are ready: connect your private Google Sheet, upload
            bank statements, and set spending rules. Takes about 10–15 minutes.
          </p>
          <ul className="space-y-1.5 text-sm text-ink-muted">
            <li className="flex gap-2">
              <span className="text-brand">1.</span> Welcome &amp; how it works
            </li>
            <li className="flex gap-2">
              <span className="text-brand">2.</span> Connect Google Sheets
            </li>
            <li className="flex gap-2">
              <span className="text-brand">3.</span> Upload statements &amp; categorize
            </li>
          </ul>
        </div>
        <div className="flex flex-col gap-2 px-5 py-5 sm:flex-row sm:justify-end">
          <button type="button" className="btn-ghost order-3 sm:order-1" onClick={onDismiss}>
            Remind me later
          </button>
          <Link
            to={onboardingPath({ preview: true })}
            className="btn-secondary order-2 inline-flex justify-center"
            onClick={onDismiss}
          >
            Preview only
          </Link>
          <button
            type="button"
            className="btn-primary order-1 inline-flex justify-center sm:order-3"
            onClick={onContinue}
          >
            Continue setup
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
