import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../../api/client";
import type { LotSummary } from "../../../api/types";

export type TickerLotsState = {
  summary: LotSummary | null;
  loading: boolean;
  error: string | null;
  retry: () => void;
};

function emptySummary(ticker: string): LotSummary {
  return {
    ticker,
    total_quantity: "0",
    quantity_tax_free: "0",
    quantity_pending: "0",
    cost_basis_native: "0",
    cost_basis_czk: "0",
    cost_basis_usd: "0",
    native_currency: null,
    lots: [],
  };
}

function errorDetail(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return "Failed to load lots";
}

/**
 * Open lots for the selected ticker. Cache lives in hook state so leaving
 * /investments drops it; marks-only soft ticks must not refetch FIFO rows.
 */
export function useTickerLots(ticker: string | null): TickerLotsState {
  const [cache, setCache] = useState<Record<string, LotSummary>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cacheRef = useRef(cache);
  cacheRef.current = cache;
  const genRef = useRef(0);

  const load = useCallback(async (symbol: string, bypassCache: boolean) => {
    if (!bypassCache && cacheRef.current[symbol]) {
      genRef.current += 1;
      setError(null);
      setLoading(false);
      return;
    }
    const gen = ++genRef.current;
    setLoading(true);
    setError(null);
    try {
      const res = await api.lots({ ticker: symbol, open_only: true });
      if (gen !== genRef.current) return;
      const summary = res.summaries[0] ?? emptySummary(symbol);
      setCache((prev) => ({ ...prev, [symbol]: summary }));
    } catch (err) {
      if (gen !== genRef.current) return;
      setError(errorDetail(err));
    } finally {
      if (gen === genRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!ticker) {
      genRef.current += 1;
      setLoading(false);
      setError(null);
      return;
    }
    void load(ticker, false);
  }, [ticker, load]);

  useEffect(() => {
    const onPrices = (ev: Event) => {
      const soft =
        (ev as CustomEvent<{ soft?: boolean }>).detail?.soft === true;
      // Layout 90s ticks only move marks; lot rows change on hard refresh/upload.
      if (soft) return;
      setCache({});
      if (ticker) void load(ticker, true);
    };
    window.addEventListener("prices-updated", onPrices);
    return () => window.removeEventListener("prices-updated", onPrices);
  }, [ticker, load]);

  const retry = useCallback(() => {
    if (!ticker) return;
    setCache((prev) => {
      const next = { ...prev };
      delete next[ticker];
      return next;
    });
    void load(ticker, true);
  }, [ticker, load]);

  return {
    summary: ticker ? (cache[ticker] ?? null) : null,
    loading,
    error,
    retry,
  };
}
