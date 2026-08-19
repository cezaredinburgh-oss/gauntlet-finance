import { useState } from "react";
import { api } from "../../api/client";
import type { Category } from "../../api/types";
import { Spinner } from "../../components/Spinner";

const NECESSITIES = [
  { value: "Discretionary", label: "Discretionary" },
  { value: "VariableNecessity", label: "Variable" },
  { value: "Fixed", label: "Fixed" },
] as const;

const LIFE_DOMAINS = [
  "Housing",
  "Debt",
  "Transport",
  "Food",
  "Subscriptions",
  "Health",
  "Income",
  "Transfers",
  "Investments",
  "Hobbies",
  "Business",
  "Cash",
  "Shopping",
  "Entertainment",
  "Education",
  "Fees",
  "Other",
] as const;

export function CreateCategoryInline({
  catsSorted,
  disabled,
  onCreated,
}: {
  catsSorted: Category[];
  disabled?: boolean;
  onCreated: (cat: Category) => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [parentId, setParentId] = useState("");
  const [necessity, setNecessity] = useState("Discretionary");
  const [lifeDomain, setLifeDomain] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!open) {
    return (
      <button
        type="button"
        className="text-[11px] text-brand hover:underline disabled:opacity-40"
        disabled={disabled}
        onClick={() => setOpen(true)}
      >
        + New category
      </button>
    );
  }

  async function save() {
    if (!name.trim()) return;
    const parent = catsSorted.find((c) => c.id === parentId);
    const domain = parent?.life_domain || lifeDomain;
    if (!domain) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api.createCategory({
        name: name.trim(),
        necessity,
        life_domain: domain,
        parent_id: parentId || null,
        is_income: parent?.is_income ?? false,
        is_transfer: parent?.is_transfer ?? false,
        sort_order: 500,
      });
      onCreated(r.item);
      setName("");
      setLifeDomain("");
      setParentId("");
      setOpen(false);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Create failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-1 space-y-1.5 rounded-lg border border-white/10 bg-black/20 p-2">
      <input
        className="input py-1 text-xs"
        placeholder="Category name"
        value={name}
        onChange={(e) => {
          const next = e.target.value;
          setName(next);
          if (!parentId && !lifeDomain && /^travel$/i.test(next.trim())) {
            setLifeDomain("Entertainment");
          }
        }}
      />
      <div className="flex flex-wrap gap-1.5">
        <select
          className="input max-w-[10rem] py-1 text-xs"
          value={parentId}
          onChange={(e) => setParentId(e.target.value)}
        >
          <option value="">No parent</option>
          {catsSorted.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        {!parentId ? (
          <select
            className="input max-w-[9rem] py-1 text-xs"
            value={lifeDomain}
            onChange={(e) => setLifeDomain(e.target.value)}
          >
            <option value="">Select domain</option>
            {LIFE_DOMAINS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        ) : null}
        <select
          className="input max-w-[8rem] py-1 text-xs"
          value={necessity}
          onChange={(e) => setNecessity(e.target.value)}
        >
          {NECESSITIES.map((n) => (
            <option key={n.value} value={n.value}>
              {n.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn-primary text-xs"
          disabled={busy || !name.trim() || (!parentId && !lifeDomain)}
          onClick={() => void save()}
        >
          {busy ? <Spinner className="h-3 w-3 border-t-slate-900" /> : null}
          Add
        </button>
        <button type="button" className="btn-ghost text-xs" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      {err ? <p className="text-[11px] text-danger">{err}</p> : null}
    </div>
  );
}
