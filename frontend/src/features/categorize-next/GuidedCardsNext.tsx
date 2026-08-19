import { ListChecks, Save, Tags, X } from "lucide-react";
import { Spinner } from "../../components/Spinner";
import { cn } from "../../lib/cn";

export function NextStepsCardNext({
  categoryName,
  vendorLabel,
  similarCount,
  rulePreview,
  ruleWarning,
  ruleMatchCount,
  busy,
  isReadOnly,
  canSaveRule,
  onReview,
  onApplySimilar,
  onSaveRule,
  onDismiss,
}: {
  categoryName: string;
  vendorLabel: string;
  similarCount: number;
  rulePreview: string;
  ruleWarning: string | null;
  ruleMatchCount: number;
  busy: boolean;
  isReadOnly: boolean;
  canSaveRule: boolean;
  onReview: () => void;
  onApplySimilar: () => void;
  onSaveRule: () => void;
  onDismiss: () => void;
}) {
  const hasSimilar = similarCount > 0;
  return (
    <div className="card min-w-0 max-w-full space-y-3 border-brand/25 p-4">
      <div className="flex min-w-0 items-start gap-2">
        <span className="rounded-lg bg-brand/15 p-2 text-brand">
          <Tags className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">Next steps</p>
          <p className="break-words text-sm text-ink-muted">
            Assigned <span className="font-medium text-ink">{categoryName}</span>
            {vendorLabel ? ` to ${vendorLabel}` : ""}.
            {hasSimilar
              ? ` ${similarCount} similar residual row${similarCount === 1 ? "" : "s"} found.`
              : " No other residual matches on this list."}
          </p>
        </div>
        <button
          type="button"
          className="btn-ghost p-2"
          aria-label="Dismiss"
          disabled={busy}
          onClick={onDismiss}
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex min-w-0 flex-wrap gap-2">
        <button
          type="button"
          className="btn-secondary justify-center text-sm"
          disabled={busy || !hasSimilar}
          onClick={onReview}
        >
          <ListChecks className="h-3.5 w-3.5" />
          Review similar{hasSimilar ? ` (${similarCount})` : ""}
        </button>
        <button
          type="button"
          className="btn-secondary justify-center text-sm"
          disabled={busy || isReadOnly || !hasSimilar}
          onClick={onApplySimilar}
        >
          Apply to {hasSimilar ? similarCount : 0} similar
        </button>
        <button
          type="button"
          className="btn-primary justify-center text-sm"
          disabled={busy || isReadOnly || !canSaveRule}
          onClick={onSaveRule}
        >
          {busy ? <Spinner className="h-4 w-4 border-t-slate-900" /> : <Save className="h-3.5 w-3.5" />}
          {hasSimilar ? "Apply + save rule" : "Save rule"}
        </button>
      </div>

      <p className="break-words text-xs text-ink-faint">
        {hasSimilar
          ? "High confidence: Apply + save rule categorizes the similar rows and writes the rule in one click."
          : "Rule only — nothing left to apply on this list."}
      </p>
      {rulePreview && (
        <p className="break-words text-sm text-ink">
          {rulePreview}
          <span className="text-ink-faint">
            {" "}
            · preview {ruleMatchCount} match{ruleMatchCount === 1 ? "" : "es"}
          </span>
        </p>
      )}
      {ruleWarning && (
        <p className="rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
          {ruleWarning}
        </p>
      )}
    </div>
  );
}

export function ReviewSimilarCardNext({
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
    <div className="card min-w-0 max-w-full space-y-3 border-brand/40 p-4">
      <div className="min-w-0">
        <p className="font-semibold text-brand">Reviewing similar transactions</p>
        <p className="break-words text-sm text-ink-muted">
          Residual candidates, A–Z. Uncheck false positives, then assign{" "}
          <span className="font-medium text-ink">{categoryName}</span>.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={cn("btn-primary")}
          disabled={busy || isReadOnly}
          onClick={onAssign}
        >
          {busy ? <Spinner className="h-4 w-4 border-t-slate-900" /> : null}
          Assign {categoryName} to {selectedCount} selected
        </button>
        <button type="button" className="btn-ghost" disabled={busy} onClick={onCancel}>
          Back
        </button>
      </div>
    </div>
  );
}
