import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { DashboardSummary } from "../api/types";
import { SPENDING_DESK } from "../auth/labDesk";
import { EmptyState, PageLoader } from "../components/Spinner";
import type { TimeframeValue } from "../components/TimeframePicker";
import type { CategoryBar } from "../features/spending-next/categoryBars";
import { honestyChips } from "../features/spending-next/honestyChips";
import { SpendingMixCard } from "../features/spending-next/SpendingMixCard";
import { transactionsDrilldownUrl } from "../features/spending-next/transactionsDrilldown";
import { LabNextChrome } from "../lab-chrome/LabNextChrome";
import {
  loadStoredSpendingTimeframe,
  saveStoredSpendingTimeframe,
} from "../lib/timeframe";

/** Lab next Spending: necessity mix + pulse in one card. Same dashboard fetch as classic. */
export function NewEtSpendingPageNext() {
  const navigate = useNavigate();
  const [tf, setTf] = useState<TimeframeValue>(() => loadStoredSpendingTimeframe());
  const [dash, setDash] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);

  const onTimeframeChange = (next: TimeframeValue) => {
    setTf(next);
    saveStoredSpendingTimeframe(next);
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const dsum = await api.dashboard({
          date_from: tf.from ?? undefined,
          date_to: tf.to,
          period_key: tf.key,
        });
        if (!cancelled) setDash(dsum);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tf, reloadTick]);

  const honesty = useMemo(() => {
    if (!dash) return { chips: [], uncatCard: false };
    return honestyChips({
      internalTransferCount: dash.cashflow.internal_transfer_count,
      unconvertedCount: dash.cashflow.unconverted_count,
      uncategorizedPct: dash.spending?.uncategorized_pct ?? 0,
    });
  }, [dash]);

  const uncatPct = dash?.spending?.uncategorized_pct ?? 0;

  function openCategoryTransactions(bar: CategoryBar) {
    const url = transactionsDrilldownUrl(tf, bar);
    if (url) navigate(url);
  }

  return (
    <LabNextChrome config={SPENDING_DESK} label="Spending desk">
      {loading && !dash ? (
        <PageLoader label="Loading spending…" />
      ) : error && !dash ? (
        <EmptyState
          title="Couldn’t load spending"
          description={error}
          action={
            <button
              type="button"
              className="btn-primary"
              onClick={() => setReloadTick((n) => n + 1)}
            >
              Retry
            </button>
          }
        />
      ) : dash ? (
        <>
          {honesty.uncatCard ? (
            <div className="card min-w-0 max-w-full border-warn/30 bg-warn/10 p-4">
              <p className="min-w-0 max-w-full break-words text-sm text-warn">
                Most spend is uncategorized ({uncatPct.toFixed(0)}%). Category bars
                will improve after categorization.
              </p>
              <Link
                to="/expenses/categorize"
                className="mt-2 inline-block font-semibold text-warn underline"
              >
                Open Categorize
              </Link>
            </div>
          ) : null}

          <SpendingMixCard
            tf={tf}
            onTimeframeChange={onTimeframeChange}
            dash={dash}
            loading={loading}
            chips={honesty.chips}
            onBarClick={openCategoryTransactions}
          />

          <div className="flex flex-wrap gap-3 text-xs">
            <Link to="/expenses/categorize" className="font-medium text-brand hover:underline">
              Categorize transactions →
            </Link>
            <Link to="/" className="text-ink-muted hover:text-ink hover:underline">
              Executive dashboard
            </Link>
          </div>
        </>
      ) : null}
    </LabNextChrome>
  );
}
