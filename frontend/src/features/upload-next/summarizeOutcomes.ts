import type { AiMapStatementResult, UploadResult } from "../../api/types";

export type FileOutcome = {
  fileName: string;
  result?: UploadResult;
  error?: string;
  /** SHA for AI map after detect failure (or re-upload path) */
  mapSha?: string;
  mapPreview?: AiMapStatementResult | null;
  mapError?: string;
  mapBusy?: boolean;
  importBusy?: boolean;
};

export function summarizeOutcomes(
  outcomes: FileOutcome[],
): { headline: string; detail: string } | null {
  if (!outcomes.length) return null;
  let imported = 0;
  let already = 0;
  let failed = 0;
  let other = 0;
  let tx = 0;
  let ev = 0;
  for (const o of outcomes) {
    if (o.error || !o.result) {
      failed += 1;
      continue;
    }
    const s = o.result.status;
    if (s === "imported") imported += 1;
    else if (s === "already_imported") already += 1;
    else if (s === "error" || s === "failed") failed += 1;
    else other += 1;
    tx += o.result.transactions_written || 0;
    ev += o.result.events_written || 0;
  }
  const parts = [`${outcomes.length} file${outcomes.length === 1 ? "" : "s"}`];
  if (imported) parts.push(`${imported} imported`);
  if (already) parts.push(`${already} already imported`);
  if (failed) parts.push(`${failed} failed`);
  if (other) parts.push(`${other} other`);
  const detailParts: string[] = [];
  if (tx) detailParts.push(`${tx} new tx`);
  if (ev) detailParts.push(`${ev} new events`);
  return { headline: parts.join(" · "), detail: detailParts.join(" · ") };
}

export function thisBatchShaSet(outcomes: FileOutcome[]): Set<string> {
  const set = new Set<string>();
  for (const o of outcomes) {
    const sha = o.result?.content_sha256 || o.mapSha;
    if (sha) set.add(sha);
  }
  return set;
}
