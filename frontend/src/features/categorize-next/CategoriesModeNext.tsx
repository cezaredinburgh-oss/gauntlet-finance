import { useMemo, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import type { Category } from "../../api/types";
import { Spinner } from "../../components/Spinner";

const NECESSITIES = [
  { value: "Fixed", label: "Fixed" },
  { value: "VariableNecessity", label: "Variable" },
  { value: "Discretionary", label: "Discretionary" },
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

type Draft = {
  name: string;
  necessity: string;
  life_domain: string;
  parent_id: string;
  is_income: boolean;
  is_transfer: boolean;
  sort_order: number;
};

const EMPTY_DRAFT: Draft = {
  name: "",
  necessity: "Discretionary",
  life_domain: "Other",
  parent_id: "",
  is_income: false,
  is_transfer: false,
  sort_order: 500,
};

function draftFrom(c: Category): Draft {
  return {
    name: c.name,
    necessity: c.necessity,
    life_domain: c.life_domain,
    parent_id: c.parent_id || "",
    is_income: c.is_income,
    is_transfer: c.is_transfer,
    sort_order: c.sort_order,
  };
}

export function CategoriesModeNext({
  cats,
  isReadOnly,
  onChanged,
}: {
  cats: Category[];
  isReadOnly: boolean;
  onChanged: () => Promise<void>;
}) {
  const [creating, setCreating] = useState(false);
  const [createDraft, setCreateDraft] = useState<Draft>(EMPTY_DRAFT);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<Draft | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [reassignTo, setReassignTo] = useState("");
  const [cascadeChildren, setCascadeChildren] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const catsSorted = useMemo(
    () =>
      cats.slice().sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name)),
    [cats],
  );
  const catMap = useMemo(() => {
    const m = new Map<string, Category>();
    cats.forEach((c) => m.set(c.id, c));
    return m;
  }, [cats]);

  async function onCreate() {
    if (!createDraft.name.trim()) return;
    setBusyId("create");
    setMsg(null);
    try {
      await api.createCategory({
        name: createDraft.name.trim(),
        necessity: createDraft.necessity,
        life_domain: createDraft.life_domain,
        parent_id: createDraft.parent_id || null,
        is_income: createDraft.is_income,
        is_transfer: createDraft.is_transfer,
        sort_order: createDraft.sort_order,
      });
      setCreateDraft(EMPTY_DRAFT);
      setCreating(false);
      await onChanged();
      setMsg("Category created.");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Create failed");
    } finally {
      setBusyId(null);
    }
  }

  async function onSaveEdit() {
    if (!editingId || !editDraft) return;
    setBusyId(editingId);
    setMsg(null);
    try {
      await api.updateCategory(editingId, {
        name: editDraft.name.trim(),
        necessity: editDraft.necessity,
        life_domain: editDraft.life_domain,
        parent_id: editDraft.parent_id || null,
        is_income: editDraft.is_income,
        is_transfer: editDraft.is_transfer,
        sort_order: editDraft.sort_order,
      });
      setEditingId(null);
      setEditDraft(null);
      await onChanged();
      setMsg("Category updated.");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Update failed");
    } finally {
      setBusyId(null);
    }
  }

  async function onDelete() {
    if (!deleteId) return;
    setBusyId(deleteId);
    setMsg(null);
    try {
      await api.deleteCategory(deleteId, {
        reassign_to: reassignTo || undefined,
        cascade_children: cascadeChildren,
      });
      setDeleteId(null);
      setReassignTo("");
      setCascadeChildren(false);
      await onChanged();
      setMsg("Category removed. Transactions were reassigned or left uncategorized.");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="card min-w-0 max-w-full space-y-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-ink-muted">{cats.length} categories</p>
        <button
          type="button"
          className="btn-primary text-sm"
          disabled={isReadOnly}
          onClick={() => {
            setCreating((v) => !v);
            setMsg(null);
          }}
        >
          {creating ? "Cancel" : "New category"}
        </button>
      </div>
      {msg && <p className="text-xs text-ink-muted">{msg}</p>}

      {creating && (
        <CategoryForm
          draft={createDraft}
          onChange={setCreateDraft}
          cats={catsSorted}
          excludeId={null}
          disabled={busyId === "create" || isReadOnly}
        >
          <button
            type="button"
            className="btn-primary text-sm"
            disabled={busyId === "create" || isReadOnly || !createDraft.name.trim()}
            onClick={() => void onCreate()}
          >
            {busyId === "create" ? <Spinner className="h-4 w-4 border-t-slate-900" /> : null}
            Create
          </button>
        </CategoryForm>
      )}

      <div className="overflow-x-auto rounded-xl border border-white/5">
        <table className="w-full min-w-0 text-left text-sm">
          <thead className="text-xs text-ink-faint">
            <tr>
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Necessity</th>
              <th className="px-4 py-2 font-medium">Domain</th>
              <th className="px-4 py-2 font-medium">Flags</th>
              <th className="px-4 py-2 font-medium">Sort</th>
              <th className="px-4 py-2 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {catsSorted.map((c) => {
              const parent = c.parent_id ? catMap.get(c.parent_id) : undefined;
              const isEditing = editingId === c.id && editDraft;
              return (
                <tr key={c.id}>
                  {isEditing && editDraft ? (
                    <td colSpan={6} className="px-4 py-3">
                      <CategoryForm
                        draft={editDraft}
                        onChange={setEditDraft}
                        cats={catsSorted}
                        excludeId={c.id}
                        disabled={busyId === c.id || isReadOnly}
                      >
                        <button
                          type="button"
                          className="btn-primary text-xs"
                          disabled={busyId === c.id || isReadOnly}
                          onClick={() => void onSaveEdit()}
                        >
                          Save
                        </button>
                        <button
                          type="button"
                          className="btn-ghost text-xs"
                          onClick={() => {
                            setEditingId(null);
                            setEditDraft(null);
                          }}
                        >
                          Cancel
                        </button>
                      </CategoryForm>
                    </td>
                  ) : (
                    <>
                      <td className="min-w-0 break-words px-4 py-2">
                        <div className={parent ? "pl-4" : ""}>
                          <div className="font-medium text-ink">{c.name}</div>
                          {parent && (
                            <div className="text-[11px] text-ink-faint">under {parent.name}</div>
                          )}
                        </div>
                      </td>
                      <td className="min-w-0 break-words px-4 py-2 text-ink-muted">
                        {c.necessity}
                      </td>
                      <td className="min-w-0 break-words px-4 py-2 text-ink-muted">
                        {c.life_domain}
                      </td>
                      <td className="min-w-0 break-words px-4 py-2 text-xs text-ink-muted">
                        {c.is_income ? "Income" : ""}
                        {c.is_income && c.is_transfer ? " · " : ""}
                        {c.is_transfer ? "Transfer" : ""}
                        {!c.is_income && !c.is_transfer ? "—" : ""}
                      </td>
                      <td className="px-4 py-2 font-mono text-xs">{c.sort_order}</td>
                      <td className="px-4 py-2 text-right">
                        <div className="flex flex-wrap justify-end gap-1">
                          <button
                            type="button"
                            className="btn-secondary px-2 py-0.5 text-[11px]"
                            disabled={isReadOnly}
                            onClick={() => {
                              setEditingId(c.id);
                              setEditDraft(draftFrom(c));
                              setDeleteId(null);
                            }}
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            className="btn-ghost px-2 py-0.5 text-[11px] text-danger"
                            disabled={isReadOnly}
                            onClick={() => {
                              setDeleteId(c.id);
                              setReassignTo("");
                              setCascadeChildren(false);
                              setEditingId(null);
                            }}
                          >
                            Delete
                          </button>
                        </div>
                      </td>
                    </>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {deleteId && (
        <div className="space-y-3 rounded-xl border border-danger/30 bg-danger/10 p-4">
          <p className="break-words text-sm text-ink">
            Remove <span className="font-semibold">{catMap.get(deleteId)?.name}</span>?
            Transactions stay in the ledger. Optionally move them to another category.
          </p>
          <label className="block text-xs text-ink-faint">
            Reassign transactions to
            <select
              className="input mt-1 max-w-xs py-1.5 text-sm"
              value={reassignTo}
              onChange={(e) => setReassignTo(e.target.value)}
            >
              <option value="">Leave uncategorized</option>
              {catsSorted
                .filter((c) => c.id !== deleteId)
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm text-ink-muted">
            <input
              type="checkbox"
              className="rounded border-white/20"
              checked={cascadeChildren}
              onChange={(e) => setCascadeChildren(e.target.checked)}
            />
            Also archive child categories
          </label>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-primary bg-danger/80 text-sm"
              disabled={busyId === deleteId || isReadOnly}
              onClick={() => void onDelete()}
            >
              {busyId === deleteId ? "Removing…" : "Confirm delete"}
            </button>
            <button
              type="button"
              className="btn-ghost text-sm"
              onClick={() => setDeleteId(null)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function CategoryForm({
  draft,
  onChange,
  cats,
  excludeId,
  disabled,
  children,
}: {
  draft: Draft;
  onChange: (d: Draft) => void;
  cats: Category[];
  excludeId: string | null;
  disabled: boolean;
  children: ReactNode;
}) {
  function patch(p: Partial<Draft>) {
    onChange({ ...draft, ...p });
  }
  return (
    <div className="min-w-0 space-y-3 rounded-xl border border-white/10 bg-white/[0.02] p-3">
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <label className="text-xs text-ink-faint">
          Name
          <input
            className="input mt-1 py-1.5 text-sm"
            value={draft.name}
            disabled={disabled}
            onChange={(e) => patch({ name: e.target.value })}
          />
        </label>
        <label className="text-xs text-ink-faint">
          Necessity
          <select
            className="input mt-1 py-1.5 text-sm"
            value={draft.necessity}
            disabled={disabled}
            onChange={(e) => patch({ necessity: e.target.value })}
          >
            {NECESSITIES.map((n) => (
              <option key={n.value} value={n.value}>
                {n.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-ink-faint">
          Life domain
          <select
            className="input mt-1 py-1.5 text-sm"
            value={draft.life_domain}
            disabled={disabled}
            onChange={(e) => patch({ life_domain: e.target.value })}
          >
            {LIFE_DOMAINS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-ink-faint">
          Parent
          <select
            className="input mt-1 py-1.5 text-sm"
            value={draft.parent_id}
            disabled={disabled}
            onChange={(e) => patch({ parent_id: e.target.value })}
          >
            <option value="">None (top level)</option>
            {cats
              .filter((c) => c.id !== excludeId)
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
          </select>
        </label>
        <label className="text-xs text-ink-faint">
          Sort order
          <input
            type="number"
            className="input mt-1 py-1.5 text-sm"
            value={draft.sort_order}
            disabled={disabled}
            onChange={(e) => patch({ sort_order: Number(e.target.value) || 0 })}
          />
        </label>
        <div className="flex flex-wrap items-end gap-4 pb-1">
          <label className="flex items-center gap-2 text-sm text-ink-muted">
            <input
              type="checkbox"
              className="rounded border-white/20"
              checked={draft.is_income}
              disabled={disabled}
              onChange={(e) => patch({ is_income: e.target.checked })}
            />
            Income
          </label>
          <label className="flex items-center gap-2 text-sm text-ink-muted">
            <input
              type="checkbox"
              className="rounded border-white/20"
              checked={draft.is_transfer}
              disabled={disabled}
              onChange={(e) => patch({ is_transfer: e.target.checked })}
            />
            Transfer
          </label>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">{children}</div>
    </div>
  );
}
