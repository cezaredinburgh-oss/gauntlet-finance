import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import { Spinner } from "../../components/Spinner";

type TenantUserRow = {
  id: string;
  email: string;
  role: string;
  tenant_ready?: boolean;
  spreadsheet_id?: string | null;
};

/**
 * Platform admin: migrate legacy single-tenant sheet onto a control-plane user.
 * Prefer "Bind env sheet to me" over Provision (which creates an empty ledger).
 * Copied from classic SettingsPage — do not import the frozen page.
 */
export function AdminLegacySheetSection({
  tenantReady,
  onBound,
}: {
  tenantReady: boolean;
  onBound: () => void;
}) {
  const [sheetId, setSheetId] = useState("");
  const [targetUserId, setTargetUserId] = useState("");
  const [users, setUsers] = useState<TenantUserRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const loadUsers = useCallback(async () => {
    try {
      const us = await api.listTenantUsers();
      setUsers(
        (us.items || []).map((u) => ({
          id: String(u.id ?? ""),
          email: String(u.email ?? ""),
          role: String(u.role ?? "user"),
          tenant_ready: Boolean(u.tenant_ready),
          spreadsheet_id: (u.spreadsheet_id as string | null | undefined) ?? null,
        })),
      );
    } catch {
      /* invites section may surface the same failure */
    }
  }, []);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  async function bindEnvToMe() {
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const r = await api.migrateEnvSheet();
      setMsg(
        r.status === "already_bound"
          ? `Already bound to ${r.spreadsheet_id ?? "sheet"}.`
          : `Bound env sheet ${r.spreadsheet_id ?? ""} to your account.`,
      );
      await loadUsers();
      onBound();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Migrate failed");
    } finally {
      setBusy(false);
    }
  }

  async function bindExplicit(e: FormEvent) {
    e.preventDefault();
    if (!sheetId.trim()) return;
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const r = await api.tenantBind(
        sheetId.trim(),
        targetUserId.trim() || undefined,
      );
      setMsg(`Bound ${r.spreadsheet_id ?? sheetId.trim()} successfully.`);
      setSheetId("");
      await loadUsers();
      onBound();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bind failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card min-w-0 space-y-4 p-5">
      <div>
        <h2 className="text-pretty break-words text-sm font-semibold text-brand">
          Admin · Legacy sheet
        </h2>
        <p className="mt-1 text-pretty break-words text-xs text-ink-muted">
          Attach an existing Google Sheet to a user after multi-tenant cutover. Do{" "}
          <strong className="text-ink">not</strong> use Provision ledger if you want to keep
          historical data — that creates a new empty sheet.
        </p>
        {tenantReady ? (
          <p className="mt-2 text-pretty break-words text-xs text-ok">
            Your account already has a sheet bound.
          </p>
        ) : (
          <p className="mt-2 text-pretty break-words text-xs text-warn">
            Your account has no sheet yet — bind the legacy production id before using the app.
          </p>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-primary"
          disabled={busy}
          onClick={() => void bindEnvToMe()}
        >
          {busy ? <Spinner /> : null}
          Bind env SPREADSHEET_ID to me
        </button>
      </div>

      <form className="space-y-3" onSubmit={(e) => void bindExplicit(e)}>
        <div>
          <label className="label" htmlFor="legacy-sheet-id">
            Spreadsheet ID or Google Sheets URL
          </label>
          <input
            id="legacy-sheet-id"
            className="input w-full"
            type="text"
            placeholder="1BxiM… or https://docs.google.com/spreadsheets/d/…"
            value={sheetId}
            onChange={(e) => setSheetId(e.target.value)}
            autoComplete="off"
          />
        </div>
        <div>
          <label className="label" htmlFor="legacy-target-user">
            Target user (optional — default: you)
          </label>
          <select
            id="legacy-target-user"
            className="input w-full"
            value={targetUserId}
            onChange={(e) => setTargetUserId(e.target.value)}
          >
            <option value="">Myself (signed-in admin)</option>
            {users
              .filter((u) => u.id)
              .map((u) => (
                <option key={u.id} value={u.id}>
                  {u.email}
                  {u.tenant_ready ? " · ready" : " · no sheet"}
                  {u.role === "platform_admin" ? " · admin" : ""}
                </option>
              ))}
          </select>
        </div>
        <button type="submit" className="btn-secondary" disabled={busy || !sheetId.trim()}>
          {busy ? <Spinner /> : null}
          Bind spreadsheet
        </button>
      </form>

      {msg && <p className="text-pretty break-words text-sm text-ok">{msg}</p>}
      {error && <p className="text-pretty break-words text-sm text-danger">{error}</p>}
    </section>
  );
}
