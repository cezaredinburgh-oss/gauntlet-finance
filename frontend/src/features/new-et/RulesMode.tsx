import { useMemo, useState } from "react";
import { Tags } from "lucide-react";
import { api } from "../../api/client";
import type { Category, CategoryRule } from "../../api/types";
import { Spinner } from "../../components/Spinner";

const MATCH_FIELDS = [
  "merchant",
  "description",
  "original_description",
  "counterparty_name",
  "source_institution",
] as const;

const MATCH_TYPES = [
  "contains",
  "exact",
  "exact_case",
  "starts_with",
  "regex",
] as const;

type RuleDraft = {
  priority: number;
  match_field: string;
  match_type: string;
  match_value: string;
  category_id: string;
  institution_scope: string;
  set_internal_transfer: boolean;
  is_active: boolean;
};

const EMPTY_CREATE: RuleDraft = {
  priority: 100,
  match_field: "merchant",
  match_type: "contains",
  match_value: "",
  category_id: "",
  institution_scope: "",
  set_internal_transfer: false,
  is_active: true,
};

export function RulesMode({
  rules,
  catsSorted,
  catMap,
  isReadOnly,
  onChanged,
}: {
  rules: CategoryRule[];
  catsSorted: Category[];
  catMap: Map<string, Category>;
  isReadOnly: boolean;
  onChanged: () => Promise<void>;
}) {
  const [creating, setCreating] = useState(false);
  const [createDraft, setCreateDraft] = useState<RuleDraft>(EMPTY_CREATE);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<RuleDraft | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function onCreate() {
    if (!createDraft.match_value.trim() || !createDraft.category_id) return;
    setBusyId("create");
    setMsg(null);
    try {
      await api.createCategoryRule({
        priority: createDraft.priority,
        match_field: createDraft.match_field,
        match_type: createDraft.match_type,
        match_value: createDraft.match_value.trim(),
        category_id: createDraft.category_id,
        institution_scope: createDraft.institution_scope.trim() || undefined,
        set_internal_transfer: createDraft.set_internal_transfer,
        is_active: createDraft.is_active,
      });
      setCreateDraft(EMPTY_CREATE);
      setCreating(false);
      await onChanged();
      setMsg("Rule saved.");
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
      await api.updateCategoryRule(editingId, {
        priority: editDraft.priority,
        match_field: editDraft.match_field,
        match_type: editDraft.match_type,
        match_value: editDraft.match_value.trim(),
        category_id: editDraft.category_id,
        institution_scope: editDraft.institution_scope.trim() || null,
        set_internal_transfer: editDraft.set_internal_transfer,
        is_active: editDraft.is_active,
      });
      setEditingId(null);
      setEditDraft(null);
      await onChanged();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Update failed");
    } finally {
      setBusyId(null);
    }
  }

  async function onRemove(id: string, label: string) {
    if (!window.confirm(`Remove rule “${label}”?`)) return;
    setBusyId(id);
    setMsg(null);
    try {
      await api.deleteCategoryRule(id);
      await onChanged();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Remove failed");
    } finally {
      setBusyId(null);
    }
  }

  type RuleSort = "priority" | "match" | "category" | "scope" | "flags";
  const [sortKey, setSortKey] = useState<RuleSort>("priority");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  function toggleSort(key: RuleSort) {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir(key === "priority" ? "asc" : "asc");
    }
  }

  const sorted = useMemo(() => {
    const rows = rules.slice();
    const dir = sortDir === "asc" ? 1 : -1;
    rows.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "priority") cmp = a.priority - b.priority;
      else if (sortKey === "match") {
        cmp = `${a.match_field} ${a.match_value}`.localeCompare(
          `${b.match_field} ${b.match_value}`,
        );
      } else if (sortKey === "category") {
        cmp = (catMap.get(a.category_id)?.name || "").localeCompare(
          catMap.get(b.category_id)?.name || "",
        );
      } else if (sortKey === "scope") {
        cmp = (a.institution_scope || "").localeCompare(b.institution_scope || "");
      } else {
        cmp = Number(b.is_active) - Number(a.is_active);
      }
      return cmp * dir;
    });
    return rows;
  }, [rules, sortKey, sortDir, catMap]);

  function SortTh({
    id,
    children,
    right,
  }: {
    id: RuleSort;
    children: string;
    right?: boolean;
  }) {
    const active = sortKey === id;
    return (
      <th className={`px-4 py-2 font-medium ${right ? "text-right" : ""}`}>
        <button
          type="button"
          className={`hover:text-ink ${active ? "text-ink" : ""}`}
          onClick={() => toggleSort(id)}
        >
          {children}
          {active ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
        </button>
      </th>
    );
  }

  return (
    <div className="card space-y-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <span className="rounded-lg bg-brand/15 p-2 text-brand">
            <Tags className="h-4 w-4" />
          </span>
          <div>
            <h2 className="font-semibold">Category rules</h2>
            <p className="text-sm text-ink-muted">
              Match patterns that auto-fill on import. Create and edit here — they do not
              overwrite manual overrides.
            </p>
          </div>
        </div>
        <button
          type="button"
          className="btn-primary text-sm"
          disabled={isReadOnly}
          onClick={() => {
            setCreating((v) => !v);
            setMsg(null);
          }}
        >
          {creating ? "Cancel" : "New rule"}
        </button>
      </div>
      {msg && <p className="text-xs text-ink-muted">{msg}</p>}

      {creating && (
        <RuleForm
          draft={createDraft}
          onChange={setCreateDraft}
          catsSorted={catsSorted}
          disabled={busyId === "create" || isReadOnly}
        >
          <button
            type="button"
            className="btn-primary text-sm"
            disabled={
              busyId === "create" ||
              isReadOnly ||
              !createDraft.match_value.trim() ||
              !createDraft.category_id
            }
            onClick={() => void onCreate()}
          >
            {busyId === "create" ? <Spinner className="h-4 w-4 border-t-slate-900" /> : null}
            Save rule
          </button>
        </RuleForm>
      )}

      {sorted.length === 0 ? (
        <p className="text-sm text-ink-muted">No rules yet. Create one above.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-white/5">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="text-xs text-ink-faint">
              <tr>
                <SortTh id="priority">Prio</SortTh>
                <SortTh id="match">Match</SortTh>
                <SortTh id="category">Category</SortTh>
                <SortTh id="scope">Scope</SortTh>
                <SortTh id="flags">Flags</SortTh>
                <th className="px-4 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {sorted.map((r) => {
                const isEditing = editingId === r.id && editDraft;
                return (
                  <tr key={r.id} className={!r.is_active ? "opacity-50" : undefined}>
                    {isEditing && editDraft ? (
                      <td colSpan={6} className="px-4 py-3">
                        <RuleForm
                          draft={editDraft}
                          onChange={setEditDraft}
                          catsSorted={catsSorted}
                          disabled={busyId === r.id || isReadOnly}
                        >
                          <button
                            type="button"
                            className="btn-primary text-xs"
                            disabled={busyId === r.id || isReadOnly}
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
                        </RuleForm>
                      </td>
                    ) : (
                      <>
                        <td className="px-4 py-2 font-mono text-xs">{r.priority}</td>
                        <td className="px-4 py-2">
                          <div className="text-xs text-ink-faint">
                            {r.match_field} · {r.match_type}
                          </div>
                          <div className="font-medium">{r.match_value}</div>
                        </td>
                        <td className="px-4 py-2">
                          {catMap.get(r.category_id)?.name || r.category_id.slice(0, 8)}
                        </td>
                        <td className="px-4 py-2 text-xs text-ink-muted">
                          {r.institution_scope || "All institutions"}
                        </td>
                        <td className="px-4 py-2 text-xs text-ink-muted">
                          {r.is_active ? "Active" : "Off"}
                          {r.set_internal_transfer ? " · Internal xfer" : ""}
                        </td>
                        <td className="px-4 py-2 text-right">
                          <div className="flex justify-end gap-1">
                            <button
                              type="button"
                              className="btn-secondary px-2 py-0.5 text-[11px]"
                              disabled={isReadOnly}
                              onClick={() => {
                                setEditingId(r.id);
                                setEditDraft({
                                  priority: r.priority,
                                  match_field: r.match_field,
                                  match_type: r.match_type,
                                  match_value: r.match_value,
                                  category_id: r.category_id,
                                  institution_scope: r.institution_scope || "",
                                  set_internal_transfer: r.set_internal_transfer,
                                  is_active: r.is_active,
                                });
                              }}
                            >
                              Edit
                            </button>
                            <button
                              type="button"
                              className="btn-ghost px-2 py-0.5 text-[11px] text-danger"
                              disabled={busyId === r.id || isReadOnly}
                              onClick={() => void onRemove(r.id, r.match_value)}
                            >
                              Remove
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
      )}
    </div>
  );
}

function RuleForm({
  draft,
  onChange,
  catsSorted,
  disabled,
  children,
}: {
  draft: RuleDraft;
  onChange: (d: RuleDraft) => void;
  catsSorted: Category[];
  disabled: boolean;
  children: React.ReactNode;
}) {
  function patch(p: Partial<RuleDraft>) {
    onChange({ ...draft, ...p });
  }
  return (
    <div className="space-y-3 rounded-xl border border-white/10 bg-white/[0.02] p-3">
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <label className="text-xs text-ink-faint">
          Field
          <select
            className="input mt-1 py-1.5 text-sm"
            value={draft.match_field}
            disabled={disabled}
            onChange={(e) => patch({ match_field: e.target.value })}
          >
            {MATCH_FIELDS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-ink-faint">
          Type
          <select
            className="input mt-1 py-1.5 text-sm"
            value={draft.match_type}
            disabled={disabled}
            onChange={(e) => patch({ match_type: e.target.value })}
          >
            {MATCH_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-ink-faint">
          Value
          <input
            className="input mt-1 py-1.5 text-sm"
            value={draft.match_value}
            disabled={disabled}
            onChange={(e) => patch({ match_value: e.target.value })}
          />
        </label>
        <label className="text-xs text-ink-faint">
          Category
          <select
            className="input mt-1 py-1.5 text-sm"
            value={draft.category_id}
            disabled={disabled}
            onChange={(e) => patch({ category_id: e.target.value })}
          >
            <option value="">Choose…</option>
            {catsSorted.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-ink-faint">
          Institution scope
          <input
            className="input mt-1 py-1.5 text-sm"
            placeholder="All institutions"
            value={draft.institution_scope}
            disabled={disabled}
            onChange={(e) => patch({ institution_scope: e.target.value })}
          />
        </label>
        <label className="text-xs text-ink-faint">
          Priority
          <input
            type="number"
            className="input mt-1 py-1.5 text-sm"
            value={draft.priority}
            disabled={disabled}
            onChange={(e) => patch({ priority: Number(e.target.value) || 0 })}
          />
        </label>
        <div className="flex flex-wrap items-end gap-4 pb-1">
          <label className="flex items-center gap-2 text-sm text-ink-muted">
            <input
              type="checkbox"
              className="rounded border-white/20"
              checked={draft.is_active}
              disabled={disabled}
              onChange={(e) => patch({ is_active: e.target.checked })}
            />
            Active
          </label>
          <label className="flex items-center gap-2 text-sm text-ink-muted">
            <input
              type="checkbox"
              className="rounded border-white/20"
              checked={draft.set_internal_transfer}
              disabled={disabled}
              onChange={(e) => patch({ set_internal_transfer: e.target.checked })}
            />
            Set internal transfer
          </label>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">{children}</div>
    </div>
  );
}
