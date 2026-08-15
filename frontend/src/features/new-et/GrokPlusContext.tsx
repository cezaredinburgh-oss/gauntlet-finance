import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiError, api } from "../../api/client";
import type { Category } from "../../api/types";
import { estimateUsd } from "../../lib/aiCost";
import {
  GROK_PLUS_BATCH,
  GROK_PLUS_SESSION_CAP,
  mergePlusBatch,
  pickLatestMatch,
} from "../../lib/grokPlus";
import type { VendorBucket } from "../../lib/ruleSuggest";

export type GrokPlusPhase = "idle" | "running" | "paused" | "caught_up" | "error";

export type GrokPlusLastMatch = {
  label: string;
  categoryName: string;
};

export type GrokPlusApi = {
  enabled: boolean;
  started: boolean;
  phase: GrokPlusPhase;
  buckets: VendorBucket[];
  message: string | null;
  lastMatch: GrokPlusLastMatch | null;
  lastBatchAdded: number;
  sessionTokens: number;
  sessionCostUsd: number;
  dayQuotaUsed: number;
  dayQuotaCap: number;
  dayCostUsd: number;
  model: string | null;
  start: (cats?: Category[]) => void;
  pause: () => void;
  resume: (cats?: Category[]) => void;
  consumeKeys: (keys: string[]) => void;
};

const STORAGE_KEY = "gauntlet.grokplus.session";

type Persisted = {
  buckets: VendorBucket[];
  exclude: string[];
  consumed: string[];
  sessionPrompt: number;
  sessionCompletion: number;
  sessionTokens: number;
  sessionCostUsd: number;
  dayQuotaUsed: number;
  dayQuotaCap: number;
  model: string | null;
  lastMatch: GrokPlusLastMatch | null;
  lastBatchAdded: number;
  batchCount: number;
  message: string | null;
};

const GrokPlusContext = createContext<GrokPlusApi | null>(null);

function readPersisted(): Persisted | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Persisted;
    if (!Array.isArray(parsed.buckets)) return null;
    return parsed;
  } catch {
    return null;
  }
}

function writePersisted(data: Persisted): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch {
    /* private mode */
  }
}

const IDLE_API: GrokPlusApi = {
  enabled: false,
  started: false,
  phase: "idle",
  buckets: [],
  message: null,
  lastMatch: null,
  lastBatchAdded: 0,
  sessionTokens: 0,
  sessionCostUsd: 0,
  dayQuotaUsed: 0,
  dayQuotaCap: 0,
  dayCostUsd: 0,
  model: null,
  start: () => undefined,
  pause: () => undefined,
  resume: () => undefined,
  consumeKeys: () => undefined,
};

export function GrokPlusProvider({
  enabled,
  children,
}: {
  enabled: boolean;
  children: ReactNode;
}) {
  const seed = useRef<Persisted | null>(enabled ? readPersisted() : null).current;

  const [phase, setPhase] = useState<GrokPlusPhase>("idle");
  const [started, setStarted] = useState(() => Boolean(seed?.buckets.length));
  const [buckets, setBuckets] = useState<VendorBucket[]>(() => seed?.buckets ?? []);
  const [message, setMessage] = useState<string | null>(() => seed?.message ?? null);
  const [lastMatch, setLastMatch] = useState<GrokPlusLastMatch | null>(
    () => seed?.lastMatch ?? null,
  );
  const [lastBatchAdded, setLastBatchAdded] = useState(() => seed?.lastBatchAdded ?? 0);
  const [sessionTokens, setSessionTokens] = useState(() => seed?.sessionTokens ?? 0);
  const [sessionCostUsd, setSessionCostUsd] = useState(() => seed?.sessionCostUsd ?? 0);
  const [dayQuotaUsed, setDayQuotaUsed] = useState(() => seed?.dayQuotaUsed ?? 0);
  const [dayQuotaCap, setDayQuotaCap] = useState(() => seed?.dayQuotaCap ?? 0);
  const [model, setModel] = useState<string | null>(() => seed?.model ?? null);

  const wantRunRef = useRef(false);
  const inFlightRef = useRef(false);
  const pauseReasonRef = useRef<"user" | "hidden" | "quota" | "error" | "cap" | null>(
    null,
  );
  const bucketsRef = useRef(buckets);
  bucketsRef.current = buckets;
  const modelRef = useRef(model);
  modelRef.current = model;
  const runRef = useRef({
    exclude: seed?.exclude ?? [],
    consumed: seed?.consumed ?? [],
    cats: [] as Category[],
    batchCount: seed?.batchCount ?? 0,
    sessionPrompt: seed?.sessionPrompt ?? 0,
    sessionCompletion: seed?.sessionCompletion ?? 0,
  });

  const dayCostUsd = useMemo(
    () => estimateUsd({ totalTokens: dayQuotaUsed, model }),
    [dayQuotaUsed, model],
  );

  useEffect(() => {
    if (!enabled || !started) return;
    const id = window.setTimeout(() => {
      const run = runRef.current;
      writePersisted({
        buckets: bucketsRef.current,
        exclude: run.exclude,
        consumed: run.consumed,
        sessionPrompt: run.sessionPrompt,
        sessionCompletion: run.sessionCompletion,
        sessionTokens,
        sessionCostUsd,
        dayQuotaUsed,
        dayQuotaCap,
        model,
        lastMatch,
        lastBatchAdded,
        batchCount: run.batchCount,
        message,
      });
    }, 200);
    return () => window.clearTimeout(id);
  }, [
    enabled,
    started,
    buckets,
    sessionTokens,
    sessionCostUsd,
    dayQuotaUsed,
    dayQuotaCap,
    model,
    lastMatch,
    lastBatchAdded,
    message,
  ]);

  const runLoop = useCallback(async () => {
    if (!enabled || inFlightRef.current) return;
    inFlightRef.current = true;
    setPhase("running");
    setStarted(true);
    if (!bucketsRef.current.length) {
      setMessage("Sorting residual vendors, then asking Grok about leftovers…");
    }
    try {
      while (wantRunRef.current) {
        if (typeof document !== "undefined" && document.hidden) {
          pauseReasonRef.current = "hidden";
          wantRunRef.current = false;
          setPhase("paused");
          setMessage("Paused while this tab is in the background.");
          break;
        }
        if (!runRef.current.cats.length) {
          try {
            const r = await api.categories();
            runRef.current.cats = r.items || [];
          } catch (e) {
            wantRunRef.current = false;
            pauseReasonRef.current = "error";
            setPhase("error");
            setMessage(e instanceof Error ? e.message : "Could not load categories.");
            break;
          }
        }
        if (runRef.current.batchCount >= GROK_PLUS_SESSION_CAP) {
          wantRunRef.current = false;
          pauseReasonRef.current = "cap";
          setPhase("paused");
          setMessage(
            `Session cap (${GROK_PLUS_SESSION_CAP} batches). Click Ask Grok+ or Resume to continue.`,
          );
          break;
        }

        let response;
        try {
          response = await api.aiVendorSuggestPlus({
            exclude_merchant_keys: [...runRef.current.exclude],
            limit: GROK_PLUS_BATCH,
          });
        } catch (e) {
          const detail =
            e instanceof ApiError
              ? e.status === 404
                ? "The API on port 8020 is old — restart Start-App, then try Ask Grok+ again."
                : e.message
              : e instanceof Error
                ? e.message
                : "Grok+ request failed";
          wantRunRef.current = false;
          pauseReasonRef.current = "error";
          setPhase("error");
          const n = bucketsRef.current.length;
          setMessage(n ? `Kept ${n} guess${n === 1 ? "" : "es"}. ${detail}` : detail);
          break;
        }

        if (response.model) setModel(response.model);
        if (typeof response.quota_used === "number") setDayQuotaUsed(response.quota_used);
        if (typeof response.quota_cap === "number") setDayQuotaCap(response.quota_cap);

        const prompt = response.prompt_tokens || 0;
        const completion = response.completion_tokens || 0;
        const used = response.tokens_used || prompt + completion;
        runRef.current.sessionPrompt += prompt;
        runRef.current.sessionCompletion += completion;
        setSessionTokens((n) => n + used);
        setSessionCostUsd(
          (n) =>
            n +
            estimateUsd({
              promptTokens: prompt,
              completionTokens: completion,
              totalTokens: used,
              model: response.model || modelRef.current,
            }),
        );

        if (!response.configured) {
          wantRunRef.current = false;
          pauseReasonRef.current = "error";
          setPhase("error");
          setMessage(
            response.message || "Grok is not configured. Set AI_ENABLED and XAI_API_KEY.",
          );
          break;
        }

        const merged = mergePlusBatch({
          prev: bucketsRef.current,
          exclude: runRef.current.exclude,
          consumed: runRef.current.consumed,
          suggestions: response.suggestions,
          vendorsSent: response.vendors_sent || [],
          cats: runRef.current.cats,
        });
        runRef.current.exclude = merged.exclude;
        runRef.current.batchCount += 1;
        bucketsRef.current = merged.buckets;
        setBuckets(merged.buckets);
        setLastBatchAdded(merged.added.length);
        const hit = pickLatestMatch(merged.added);
        if (hit) setLastMatch(hit);

        const total = merged.buckets.length;
        if (hit) {
          setMessage(
            `${hit.label} → ${hit.categoryName} · ${total} guess${total === 1 ? "" : "es"} so far`,
          );
        } else if (total) {
          setMessage(`Mapped ${total} vendor${total === 1 ? "" : "s"}… looking for more`);
        } else {
          setMessage("Matching vendors to categories…");
        }

        const sent = response.vendors_sent || [];
        if (!sent.length && merged.added.length === 0) {
          wantRunRef.current = false;
          setPhase("caught_up");
          setMessage(
            total
              ? `Caught up — ${total} guess${total === 1 ? "" : "es"} waiting.`
              : "Grok returned no vendor guesses.",
          );
          break;
        }

        if (
          response.message &&
          /limit/i.test(response.message) &&
          !response.suggestions.length
        ) {
          wantRunRef.current = false;
          pauseReasonRef.current = "quota";
          setPhase("paused");
          setMessage(response.message);
          break;
        }

        if (!wantRunRef.current) {
          setPhase("paused");
          break;
        }
      }
    } finally {
      inFlightRef.current = false;
    }
  }, [enabled]);

  const start = useCallback(
    (cats?: Category[]) => {
      if (!enabled) return;
      if (cats?.length) runRef.current.cats = cats;
      if (pauseReasonRef.current === "cap") {
        runRef.current.batchCount = 0;
      }
      pauseReasonRef.current = null;
      wantRunRef.current = true;
      setStarted(true);
      void runLoop();
    },
    [enabled, runLoop],
  );

  const pause = useCallback(() => {
    wantRunRef.current = false;
    pauseReasonRef.current = "user";
    setPhase((p) => (p === "running" ? "paused" : p));
    setMessage((m) => m || "Paused.");
  }, []);

  const resume = useCallback(
    (cats?: Category[]) => {
      start(cats);
    },
    [start],
  );

  const consumeKeys = useCallback((keys: string[]) => {
    if (!keys.length) return;
    const drop = new Set(keys);
    runRef.current.consumed = [...new Set([...runRef.current.consumed, ...keys])];
    runRef.current.exclude = [...new Set([...runRef.current.exclude, ...keys])];
    setBuckets((prev) => {
      const next = prev.filter((b) => !drop.has(b.key));
      bucketsRef.current = next;
      return next;
    });
  }, []);

  useEffect(() => {
    if (!enabled) return;
    const onVis = () => {
      if (document.hidden) {
        if (wantRunRef.current) {
          wantRunRef.current = false;
          pauseReasonRef.current = "hidden";
          setPhase("paused");
          setMessage("Paused while this tab is in the background.");
        }
        return;
      }
      if (pauseReasonRef.current === "hidden") {
        pauseReasonRef.current = null;
        wantRunRef.current = true;
        void runLoop();
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [enabled, runLoop]);

  const apiValue = useMemo<GrokPlusApi>(
    () => ({
      enabled,
      started,
      phase,
      buckets,
      message,
      lastMatch,
      lastBatchAdded,
      sessionTokens,
      sessionCostUsd,
      dayQuotaUsed,
      dayQuotaCap,
      dayCostUsd,
      model,
      start,
      pause,
      resume,
      consumeKeys,
    }),
    [
      enabled,
      started,
      phase,
      buckets,
      message,
      lastMatch,
      lastBatchAdded,
      sessionTokens,
      sessionCostUsd,
      dayQuotaUsed,
      dayQuotaCap,
      dayCostUsd,
      model,
      start,
      pause,
      resume,
      consumeKeys,
    ],
  );

  return (
    <GrokPlusContext.Provider value={apiValue}>{children}</GrokPlusContext.Provider>
  );
}

export function useGrokPlus(): GrokPlusApi {
  return useContext(GrokPlusContext) ?? IDLE_API;
}
