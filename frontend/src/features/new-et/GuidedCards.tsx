import { Sparkles, Tags, X } from "lucide-react";
import { Spinner } from "../../components/Spinner";

export function OfferSimilarCard({
  categoryName,
  vendorLabel,
  onYes,
  onNo,
}: {
  categoryName: string;
  vendorLabel: string;
  onYes: () => void;
  onNo: () => void;
}) {
  return (
    <div className="card space-y-3 border-brand/25 p-4">
      <div className="flex items-start gap-2">
        <span className="rounded-lg bg-brand/15 p-2 text-brand">
          <Sparkles className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold">Look for other transactions like this?</h2>
          <p className="text-sm text-ink-muted">
            You assigned <span className="font-medium text-ink">{categoryName}</span>
            {vendorLabel ? ` to ${vendorLabel}` : ""}. We can find similar residual rows
            (same merchant, same money direction) for you to review.
          </p>
        </div>
        <button type="button" className="btn-ghost p-2" aria-label="Dismiss" onClick={onNo}>
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn-primary" onClick={onYes}>
          Yes
        </button>
        <button type="button" className="btn-secondary" onClick={onNo}>
          No, just this
        </button>
      </div>
    </div>
  );
}

export function ReviewSimilarCard({
  categoryName,
  selectedCount,
  busy,
  isReadOnly,
  onAssign,
  onCancel,
}: {
  categoryName: string;
  selectedCount: number;
  busy: boolean;
  isReadOnly: boolean;
  onAssign: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="sticky top-14 z-30 card space-y-3 border-brand/40 bg-slate-950/95 p-4 shadow-lg backdrop-blur-md">
      <div>
        <h2 className="font-semibold text-brand">Reviewing similar transactions</h2>
        <p className="text-sm text-ink-muted">
          Residual candidates, A–Z. Uncheck false positives, then assign{" "}
          <span className="font-medium text-ink">{categoryName}</span>.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-primary"
          disabled={busy || isReadOnly}
          onClick={onAssign}
        >
          {busy ? <Spinner className="h-4 w-4 border-t-slate-900" /> : null}
          Assign {categoryName} to {selectedCount} selected
        </button>
        <button type="button" className="btn-ghost" disabled={busy} onClick={onCancel}>
          Cancel review
        </button>
      </div>
    </div>
  );
}

export function OfferRuleCard({
  plainEnglish,
  warning,
  previewCount,
  busy,
  isReadOnly,
  canSave,
  onSave,
  onDismiss,
}: {
  plainEnglish: string;
  warning: string | null;
  previewCount: number;
  busy: boolean;
  isReadOnly: boolean;
  canSave: boolean;
  onSave: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="card space-y-3 border-brand/25 p-4">
      <div className="flex items-start gap-2">
        <span className="rounded-lg bg-brand/15 p-2 text-brand">
          <Tags className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold">Save a rule for next time?</h2>
          <p className="mt-1 text-sm text-ink">{plainEnglish}</p>
          {warning && (
            <p className="mt-2 rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
              {warning}
            </p>
          )}
          <p className="mt-1 text-xs text-ink-faint">
            Preview on loaded list: would match{" "}
            <span className="font-semibold text-ink">{previewCount}</span> non-override
            transaction(s).
          </p>
        </div>
        <button type="button" className="btn-ghost p-2" aria-label="Dismiss" onClick={onDismiss}>
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-primary"
          disabled={busy || !canSave || isReadOnly}
          onClick={onSave}
        >
          {busy ? <Spinner className="h-4 w-4 border-t-slate-900" /> : null}
          Save rule
        </button>
        <button type="button" className="btn-ghost" disabled={busy} onClick={onDismiss}>
          Don&apos;t save
        </button>
      </div>
    </div>
  );
}
