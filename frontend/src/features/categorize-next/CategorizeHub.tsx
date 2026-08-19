import { Link } from "react-router-dom";
import { categorizeHref, drillParamPatch, windowParamPatch } from "./workspaceMode";

function coverageStatusLabel(status: string | null | undefined): string | null {
  if (status === "below_target") return "Below target";
  if (status === "on_target") return "On target";
  if (status === "stretch") return "Stretch";
  return null;
}

const WINDOW_CARDS: {
  win: "review" | "grokplus" | "rules" | "categories";
  title: string;
  explanation: string;
}[] = [
  {
    win: "review",
    title: "Review leftovers",
    explanation:
      "File uncategorized shops in bulk. Pick a category, Apply, or Apply + rule. Click a vendor to see its transactions.",
  },
  {
    win: "grokplus",
    title: "Ask Grok+",
    explanation:
      "Matches leftover vendors using memory, tags, then Grok. Expand a guess, check the txs, retarget misses, then Approve. Grok+ never writes the ledger.",
  },
  {
    win: "rules",
    title: "Rules",
    explanation:
      "Create or edit match patterns (merchant, description, …). Saving a rule does not apply it to existing rows or to the next upload.",
  },
  {
    win: "categories",
    title: "Categories",
    explanation:
      "Names, necessity, and domain Grok+ and rules assign into. Stable IDs — do not rename to “fix” history.",
  },
];

export function CategorizeHub({
  leftoverCount,
  categorizedCount,
  ledgerTxTotal,
  itemsLength,
  total,
  leftoverVendorCount,
  residualTxCount,
  rulesCount,
  categoriesCount,
  coveragePct,
  coverageStatus,
  progressNote,
  ladderText,
  grokPlusSupporting,
  showSetupBanner,
  onSkipSetup,
  onAskGrokPlus,
  isReadOnly,
  wipeBusy,
  onWipe,
}: {
  leftoverCount: number;
  categorizedCount: number;
  ledgerTxTotal: number;
  itemsLength: number;
  total: number;
  leftoverVendorCount: number;
  residualTxCount: number;
  rulesCount: number;
  categoriesCount: number;
  coveragePct: number | null;
  coverageStatus: string | null | undefined;
  progressNote: string | null | undefined;
  ladderText: string | null;
  grokPlusSupporting: string;
  showSetupBanner: boolean;
  onSkipSetup: () => void;
  onAskGrokPlus: () => void;
  isReadOnly: boolean;
  wipeBusy: boolean;
  onWipe: () => void;
}) {
  const honesty =
    total > itemsLength
      ? `newest ${itemsLength.toLocaleString()} of ${total.toLocaleString()} loaded`
      : `newest ${itemsLength.toLocaleString()} loaded`;
  const statusLabel = coverageStatusLabel(coverageStatus);
  const reviewHref = categorizeHref(windowParamPatch("review"));
  const rulesHref = categorizeHref(windowParamPatch("rules"));
  const categoriesHref = categorizeHref(windowParamPatch("categories"));
  const grokHref = categorizeHref(windowParamPatch("grokplus"));
  const browseHref = categorizeHref(windowParamPatch("txs"));
  const leftoverHref = categorizeHref(
    drillParamPatch({ src: "hub", category_id: "uncategorized" }),
  );
  const leftoverUsdHref = categorizeHref(
    drillParamPatch({
      src: "hub_usd",
      category_id: "uncategorized",
      expenses_only: "1",
    }),
  );

  const supporting = (win: (typeof WINDOW_CARDS)[number]["win"]): string => {
    if (win === "review") {
      return `${leftoverVendorCount.toLocaleString()} vendors · ${residualTxCount.toLocaleString()} tx on this list`;
    }
    if (win === "grokplus") return grokPlusSupporting;
    if (win === "rules") return `${rulesCount.toLocaleString()} rules`;
    return `${categoriesCount.toLocaleString()} categories`;
  };

  return (
    <div className="min-w-0 max-w-full space-y-4">
      {showSetupBanner ? (
        <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2 text-sm text-ink-muted">
          <span className="min-w-0 break-words">
            Finish setup — check <span className="font-medium text-ink">Categories</span>{" "}
            (what Grok+ and rules can assign into), then{" "}
            <span className="font-medium text-ink">Rules</span> (optional patterns). Import
            does not apply rules.
          </span>
          <Link to={categoriesHref} className="font-medium text-brand hover:underline">
            Categories
          </Link>
          <Link to={rulesHref} className="font-medium text-brand hover:underline">
            Rules
          </Link>
          <button type="button" className="btn-ghost text-xs" onClick={onSkipSetup}>
            Skip
          </button>
        </div>
      ) : null}

      <section className="card min-w-0 max-w-full space-y-2 p-4">
        <p className="min-w-0 max-w-full break-words text-sm text-ink">
          <Link to={leftoverHref} className="font-medium hover:underline">
            {leftoverCount.toLocaleString()} leftover in the ledger
          </Link>
          {" · "}
          {categorizedCount.toLocaleString()} categorized
          {" · "}
          {ledgerTxTotal.toLocaleString()} in the ledger
        </p>
        <p className="min-w-0 max-w-full break-words text-sm text-ink-muted">
          <Link to={reviewHref} className="hover:text-ink hover:underline">
            {leftoverVendorCount.toLocaleString()} leftover vendors on this list
          </Link>
          {" · "}
          {honesty}
        </p>
        <p className="min-w-0 max-w-full break-words text-sm text-ink-muted">
          <Link to={rulesHref} className="hover:text-ink hover:underline">
            {rulesCount.toLocaleString()} rules
          </Link>
          {" · "}
          <Link to={categoriesHref} className="hover:text-ink hover:underline">
            {categoriesCount.toLocaleString()} categories
          </Link>
        </p>
        {coveragePct != null ? (
          <p className="min-w-0 max-w-full break-words text-sm text-ink-muted">
            <Link
              to={leftoverUsdHref}
              title="Uncategorized expenses on this list"
              className="hover:text-ink hover:underline"
            >
              180d expense coverage · {coveragePct}%
              {statusLabel ? ` · ${statusLabel}` : ""}
              {progressNote ? ` · ${progressNote}` : ""}
            </Link>
          </p>
        ) : null}
        {leftoverVendorCount > 0 && ladderText ? (
          <p className="min-w-0 max-w-full break-words text-xs text-ink-faint">{ladderText}</p>
        ) : null}
      </section>

      <section className="card min-w-0 max-w-full space-y-2 p-4">
        <h2 className="text-sm font-medium text-ink">How categorization works</h2>
        <ol className="min-w-0 max-w-full list-decimal space-y-1.5 pl-4 text-sm text-ink-muted">
          <li className="min-w-0 break-words">
            Upload tags new rows. It never writes a category. Rules do not run on import.
          </li>
          <li className="min-w-0 break-words">
            Review leftovers — file repeating shops (one row, a vendor, or save a rule).
          </li>
          <li className="min-w-0 break-words">
            Ask Grok+ — paid guesses only. Nothing is saved until you Approve.
          </li>
          <li className="min-w-0 break-words">
            Rules and Categories — teach patterns and maintain the catalog. Saving a rule
            does not recategorize the ledger. Apply + rule files those leftover rows and
            saves the pattern. It does not scan the rest of the ledger.
          </li>
        </ol>
      </section>

      <div className="grid min-w-0 max-w-full grid-cols-1 gap-3 sm:grid-cols-2">
        {WINDOW_CARDS.map((card) => {
          const href =
            card.win === "review"
              ? reviewHref
              : card.win === "grokplus"
                ? grokHref
                : card.win === "rules"
                  ? rulesHref
                  : categoriesHref;
          return (
            <Link
              key={card.win}
              to={href}
              onClick={card.win === "grokplus" ? onAskGrokPlus : undefined}
              className="card min-w-0 max-w-full space-y-1.5 p-4 transition hover:border-brand/40"
            >
              <div className="min-w-0 font-medium text-ink">{card.title}</div>
              <div className="min-w-0 break-words text-xs font-medium text-brand">
                {supporting(card.win)}
              </div>
              <p className="min-w-0 max-w-full break-words text-sm text-ink-muted">
                {card.explanation}
              </p>
            </Link>
          );
        })}
      </div>

      <div className="flex min-w-0 max-w-full flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <Link
          to={browseHref}
          className="min-w-0 break-words text-ink-muted hover:text-ink hover:underline"
        >
          Browse transactions — search, filter, and assign one-offs. Vendor, rule, and
          category clicks land here.
        </Link>
        {!isReadOnly ? (
          <button
            type="button"
            className="btn-ghost shrink-0 text-xs"
            disabled={wipeBusy}
            onClick={onWipe}
          >
            {wipeBusy ? "Resetting…" : "Reset categorization"}
          </button>
        ) : null}
      </div>
    </div>
  );
}
