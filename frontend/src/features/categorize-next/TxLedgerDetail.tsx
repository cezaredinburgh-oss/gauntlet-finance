import { useEffect, useId, useMemo, type ReactNode } from "react";
import { ArrowLeftRight, X } from "lucide-react";
import type { Category, Transaction } from "../../api/types";
import { Money } from "../../components/Money";
import { hasMoneyValue } from "../../lib/money";

function dash(value: string | null | undefined): string {
  const s = value?.trim();
  return s ? s : "—";
}

function yesNo(value: boolean | undefined): string {
  return value ? "Yes" : "No";
}

function Field({
  label,
  children,
  breakAll,
}: {
  label: string;
  children: ReactNode;
  breakAll?: boolean;
}) {
  return (
    <>
      <dt className="text-xs text-ink-faint">{label}</dt>
      <dd className={breakAll ? "min-w-0 break-all text-sm text-ink" : "min-w-0 break-words text-sm text-ink"}>
        {children}
      </dd>
    </>
  );
}

function StoredMoney({
  amount,
  currency,
  signed = false,
}: {
  amount: string | number | null | undefined;
  currency: string;
  signed?: boolean;
}) {
  if (!hasMoneyValue(amount)) return <>{"—"}</>;
  return (
    <Money
      amount={amount}
      currency={currency}
      signed={signed}
      secondaryMode="none"
      size="sm"
    />
  );
}

function categoryLine(
  id: string | null | undefined,
  catMap: Map<string, Category>,
): string {
  if (!id) return "—";
  const name = catMap.get(id)?.name;
  return name ? `${name} · ${id}` : id;
}

export function TxLedgerDetail({
  tx,
  loading,
  error,
  notFound,
  catMap,
  items,
  onClose,
  onRetry,
  onOpenTx,
}: {
  tx: Transaction | null;
  loading: boolean;
  error: string | null;
  notFound: boolean;
  catMap: Map<string, Category>;
  items: Transaction[];
  onClose: () => void;
  onRetry: () => void;
  onOpenTx: (id: string) => void;
}) {
  const titleId = useId();
  const title = tx
    ? tx.merchant || tx.description || "Transaction"
    : "Transaction";

  const pairedLeg = useMemo(() => {
    if (!tx?.transfer_group_id) return null;
    return (
      items.find(
        (row) =>
          row.id !== tx.id && row.transfer_group_id === tx.transfer_group_id,
      ) ?? null
    );
  }, [tx, items]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50">
      <button
        type="button"
        className="absolute inset-0 bg-black/60"
        aria-label="Close"
        onClick={onClose}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="fixed inset-y-0 right-0 z-50 flex max-h-[100dvh] w-full max-w-lg min-w-0 flex-col border-l border-white/10 bg-surface-raised/95 shadow-card backdrop-blur-md"
      >
        <header className="flex shrink-0 items-start gap-3 border-b border-white/10 px-4 py-3">
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="truncate text-base font-semibold text-ink">
              {title}
            </h2>
            {tx ? (
              <div className="mt-1 flex min-w-0 flex-wrap items-center gap-1.5">
                {tx.is_internal_transfer ? (
                  <span className="badge bg-brand/15 text-brand">
                    <ArrowLeftRight className="mr-1 h-3 w-3" />
                    Internal
                  </span>
                ) : null}
                {tx.category_override ? (
                  <span className="badge bg-warn/15 text-warn">Recategorized</span>
                ) : null}
                {!tx.category_id && tx.suggest_reason ? (
                  <span className="badge bg-white/10 text-ink-muted">
                    Tag: {tx.suggest_reason}
                  </span>
                ) : null}
              </div>
            ) : null}
          </div>
          <button
            type="button"
            className="btn-ghost shrink-0 p-2"
            aria-label="Close"
            onClick={onClose}
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          {loading ? (
            <p className="text-sm text-ink-muted">Loading transaction…</p>
          ) : error ? (
            <div className="space-y-3">
              <p className="text-sm text-ink">Couldn’t load transaction</p>
              <p className="break-words text-sm text-ink-muted">{error}</p>
              <button type="button" className="btn-secondary text-sm" onClick={onRetry}>
                Retry
              </button>
            </div>
          ) : notFound || !tx ? (
            <p className="text-sm text-ink-muted">
              Transaction not found. It may be archived or not in the ledger.
            </p>
          ) : (
            <dl className="grid grid-cols-[minmax(7rem,10.5rem)_1fr] gap-x-3 gap-y-3">
              <Field label="Transaction ID" breakAll>
                {tx.id}
              </Field>
              <Field label="Account ID" breakAll>
                {tx.account_id}
              </Field>
              <Field label="Booking date">{tx.booking_date}</Field>
              <Field label="Value date">{dash(tx.value_date)}</Field>
              <Field label="Amount">
                <Money
                  amount={tx.amount}
                  currency={tx.currency}
                  signed
                  secondaryMode="none"
                  size="sm"
                />
              </Field>
              <Field label="Currency">{tx.currency}</Field>
              <Field label="Amount CZK (stored)">
                <StoredMoney amount={tx.amount_czk} currency="CZK" signed />
              </Field>
              <Field label="Amount USD (stored)">
                <StoredMoney amount={tx.amount_usd} currency="USD" signed />
              </Field>
              <Field label="Fee amount">
                <StoredMoney
                  amount={tx.fee_amount}
                  currency={tx.fee_currency || tx.currency}
                />
              </Field>
              <Field label="Fee currency">{dash(tx.fee_currency)}</Field>
              <Field label="Merchant">{dash(tx.merchant)}</Field>
              <Field label="Description">{dash(tx.description)}</Field>
              <Field label="Original description">{dash(tx.original_description)}</Field>
              <Field label="Source institution">{dash(tx.source_institution)}</Field>
              <Field label="External ID" breakAll>
                {dash(tx.external_id)}
              </Field>
              <Field label="Counterparty account" breakAll>
                {dash(tx.counterparty_account)}
              </Field>
              <Field label="Counterparty name">{dash(tx.counterparty_name)}</Field>
              <Field label="Category" breakAll>
                {categoryLine(tx.category_id, catMap)}
              </Field>
              <Field label="Category override">{yesNo(tx.category_override)}</Field>
              <Field label="Internal transfer">{yesNo(tx.is_internal_transfer)}</Field>
              <Field label="Transfer group" breakAll>
                {tx.transfer_group_id ? (
                  <span className="flex min-w-0 flex-col gap-1">
                    <span className="break-all">{tx.transfer_group_id}</span>
                    {pairedLeg ? (
                      <button
                        type="button"
                        className="w-fit text-left text-brand hover:underline"
                        onClick={() => onOpenTx(pairedLeg.id)}
                      >
                        Paired leg
                      </button>
                    ) : null}
                  </span>
                ) : (
                  "—"
                )}
              </Field>
              <Field label="Original file hash" breakAll>
                {dash(tx.original_file_hash)}
              </Field>
              <Field label="Source file" breakAll>
                {dash(tx.source_file_id)}
              </Field>
              <Field label="Notes">{dash(tx.notes)}</Field>
              <Field label="Suggested category" breakAll>
                {categoryLine(tx.suggest_category_id, catMap)}
              </Field>
              <Field label="Suggest source">{dash(tx.suggest_source)}</Field>
              <Field label="Suggest reason">{dash(tx.suggest_reason)}</Field>
              <Field label="Archived">{yesNo(tx.archived)}</Field>
              <Field label="Created">{dash(tx.created_at)}</Field>
              <Field label="Updated">{dash(tx.updated_at)}</Field>
            </dl>
          )}
        </div>

        <footer className="flex shrink-0 justify-end border-t border-white/10 px-4 py-3">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Close
          </button>
        </footer>
      </aside>
    </div>
  );
}
