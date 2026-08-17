import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { DcaBoardResponse } from "../api/types";
import { EmptyState, PageLoader } from "../components/Spinner";
import { InvestmentsNextChrome } from "../features/investments/lab-chrome/InvestmentsNextChrome";
import { DcaBoardNext } from "../features/investments/dca-next/DcaBoardNext";
import { DcaHonestyStrip } from "../features/investments/dca-next/DcaHonestyStrip";

export function InvestmentsDcaPageNext() {
  const [board, setBoard] = useState<DcaBoardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (opts?: { quiet?: boolean }) => {
    const quiet = opts?.quiet ?? false;
    if (!quiet) setLoading(true);
    try {
      const r = await api.investmentsDcaOpportunities();
      setBoard(r);
      setError(null);
    } catch (e) {
      if (!quiet) setError(e instanceof Error ? e.message : "Failed");
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onPrices = () => {
      void load({ quiet: true });
    };
    window.addEventListener("prices-updated", onPrices);
    return () => window.removeEventListener("prices-updated", onPrices);
  }, [load]);

  const stocks = board?.stocks ?? [];
  const crypto = board?.crypto ?? [];

  return (
    <InvestmentsNextChrome active="dca">
      {loading && !board && <PageLoader label="Loading DCA board…" />}

      {error && !board && (
        <EmptyState
          title="Couldn’t load DCA board"
          description={error}
          action={
            <button type="button" className="btn-primary" onClick={() => void load()}>
              Retry
            </button>
          }
        />
      )}

      {board && (
        <>
          <DcaHonestyStrip board={board} />
          <DcaBoardNext
            stocks={stocks}
            crypto={crypto}
            historyAvailable={board.meta.history_available}
          />
          <p className="text-[11px] leading-relaxed text-ink-faint">
            Recipe: discount + 3M + 52w + days + log10(MV+1). Rank is server order · not
            a ticket.
          </p>
        </>
      )}
    </InvestmentsNextChrome>
  );
}
