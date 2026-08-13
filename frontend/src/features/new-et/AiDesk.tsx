import { Sparkles } from "lucide-react";
import type { AiClusterSuggestion, AiStatus, Category } from "../../api/types";
import { cn } from "../../lib/cn";

const KIND_LABEL: Record<string, string> = {
  vendor: "Vendor",
  near_identical: "Near-identical",
  internal_transfer: "Internal transfer",
  income: "Income",
  fee: "Fee",
  other: "Other",
};

export function AiDesk({
  status,
  statusError,
  clusters,
  message,
  busy,
  applyBusy,
  isReadOnly,
  catsSorted,
  categoryPicks,
  onSuggest,
  onFocus,
  onApply,
  onSkip,
  onPick,
}: {
  status: AiStatus | null;
  statusError: string | null;
  clusters: AiClusterSuggestion[];
  message: string | null;
  busy: boolean;
  applyBusy?: boolean;
  isReadOnly: boolean;
  catsSorted: Category[];
  categoryPicks: Record<string, string>;
  onSuggest: () => void;
  onFocus: (c: AiClusterSuggestion) => void;
  onApply: (c: AiClusterSuggestion) => void;
  onSkip: (c: AiClusterSuggestion) => void;
  onPick: (key: string, categoryId: string) => void;
}) {
  const statusReady = status != null || statusError != null;
  const configured = Boolean(
    status?.configured && status.enabled && status.mode !== "sandbox_demo",
  );

  return (
    <div className="card space-y-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <span className="rounded-lg bg-brand/15 p-2 text-brand">
            <Sparkles className="h-4 w-4" />
          </span>
          <div>
            <h2 className="font-semibold">AI clusters</h2>
            <p className="text-sm text-ink-muted">
              Grok proposes work piles from residual rows. Nothing is saved until you apply.
            </p>
          </div>
        </div>
        {configured && (
          <button
            type="button"
            className="btn-primary text-sm inline-flex items-center gap-1.5"
            disabled={busy || isReadOnly}
            onClick={onSuggest}
          >
            <Sparkles className="h-3.5 w-3.5" />
            {busy ? "Clustering… (can take ~1–2 min)" : "Suggest clusters"}
          </button>
        )}
      </div>

      {statusError && <p className="text-xs text-danger">{statusError}</p>}

      {statusReady && !configured && (
        <div className="rounded-xl border border-warn/30 bg-warn/10 px-4 py-3 text-sm text-warn">
          AI is not configured. Set <code className="text-ink">AI_ENABLED=true</code> and{" "}
          <code className="text-ink">XAI_API_KEY</code> on the API. New ET will not invent
          clusters without Grok.
        </div>
      )}

      {configured && message && (
        <p className="text-xs text-ink-muted">{message}</p>
      )}

      {configured && clusters.length === 0 && !busy && (
        <p className="text-sm text-ink-faint">
          No clusters yet. Click “Suggest clusters” to scan residual transactions.
        </p>
      )}

      {clusters.length > 0 && (
        <ul className="space-y-3">
          {clusters.map((c) => {
            const needsPick = c.needs_human || !c.category_id;
            const pick = categoryPicks[c.cluster_key] || "";
            return (
              <li
                key={c.cluster_key}
                className="rounded-xl border border-white/10 bg-white/[0.02] p-3"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-ink">{c.title}</span>
                      <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-muted">
                        {KIND_LABEL[c.kind] || c.kind}
                      </span>
                      {c.needs_human && (
                        <span className="rounded-full bg-warn/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-warn">
                          Needs human
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 text-xs text-ink-muted">
                      {needsPick ? (
                        <span className="text-warn">Pick a category below</span>
                      ) : (
                        <>
                          → {c.category_name}{" "}
                          <span className="text-ink-faint">
                            · {(c.confidence * 100).toFixed(0)}% · {c.sample_count} tx
                          </span>
                        </>
                      )}
                      {c.reason ? (
                        <span className="text-ink-faint"> · {c.reason}</span>
                      ) : null}
                    </div>
                  </div>
                </div>

                {needsPick && (
                  <label className="mt-2 block text-xs text-ink-faint">
                    Category
                    <select
                      className="input mt-1 max-w-xs py-1.5 text-sm"
                      value={pick}
                      onChange={(e) => onPick(c.cluster_key, e.target.value)}
                    >
                      <option value="">Choose…</option>
                      {catsSorted.map((cat) => (
                        <option key={cat.id} value={cat.id}>
                          {cat.name}
                        </option>
                      ))}
                    </select>
                  </label>
                )}

                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    className="btn-secondary text-[11px]"
                    disabled={busy || applyBusy}
                    onClick={() => onFocus(c)}
                  >
                    Show transactions
                  </button>
                  <button
                    type="button"
                    className="btn-primary text-[11px]"
                    disabled={isReadOnly || busy || applyBusy || (needsPick && !pick)}
                    onClick={() => onApply(c)}
                  >
                    Apply
                  </button>
                  <button
                    type="button"
                    className="btn-ghost text-[11px]"
                    disabled={busy || applyBusy}
                    onClick={() => onSkip(c)}
                  >
                    Skip
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {status?.quota_cap ? (
        <p className={cn("text-[10px] text-ink-faint")}>
          Quota {status.quota_used}/{status.quota_cap} tokens
        </p>
      ) : null}
    </div>
  );
}
