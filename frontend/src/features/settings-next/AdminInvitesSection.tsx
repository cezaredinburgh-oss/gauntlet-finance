import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import { Spinner } from "../../components/Spinner";

type InviteRow = {
  id: string;
  email: string;
  pending?: boolean;
  accepted_at?: string | null;
  created_at?: string;
};

/**
 * Platform admin: invite Google emails on this multi-tenant host.
 * Copied from classic SettingsPage — do not import the frozen page.
 */
export function AdminInvitesSection() {
  const [email, setEmail] = useState("");
  const [items, setItems] = useState<InviteRow[]>([]);
  const [users, setUsers] = useState<Array<{ email: string; role: string; tenant_ready?: boolean }>>(
    [],
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [inv, us] = await Promise.all([
        api.listInvites(false),
        api.listTenantUsers().catch(() => ({ items: [] })),
      ]);
      setItems((inv.items || []) as InviteRow[]);
      setUsers(
        (us.items || []).map((u) => ({
          email: String(u.email ?? ""),
          role: String(u.role ?? "user"),
          tenant_ready: Boolean(u.tenant_ready),
        })),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load invites");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function createInvite(e: FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      await api.createInvite(email.trim());
      setMsg(`Invite created for ${email.trim()}`);
      setEmail("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invite failed");
    } finally {
      setBusy(false);
    }
  }

  async function removeInvite(id: string) {
    setBusy(true);
    setError(null);
    try {
      await api.deleteInvite(id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card min-w-0 space-y-4 p-5">
      <div>
        <h2 className="text-pretty break-words text-sm font-semibold text-brand">
          Admin · Invites
        </h2>
        <p className="mt-1 text-pretty break-words text-xs text-ink-muted">
          Platform admin only. Invite Google emails so they can sign in on this multi-tenant host.
        </p>
      </div>

      <form className="flex flex-wrap gap-2" onSubmit={(e) => void createInvite(e)}>
        <input
          className="input min-w-[12rem] flex-1"
          type="email"
          placeholder="user@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <button type="submit" className="btn-primary" disabled={busy}>
          {busy ? <Spinner /> : null}
          Invite
        </button>
      </form>

      {msg && <p className="text-pretty break-words text-sm text-ok">{msg}</p>}
      {error && <p className="text-pretty break-words text-sm text-danger">{error}</p>}

      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-faint">Invites</h3>
        {items.length === 0 ? (
          <p className="mt-1 text-pretty break-words text-xs text-ink-muted">No invites yet.</p>
        ) : (
          <ul className="mt-2 space-y-1 text-sm">
            {items.map((i) => (
              <li
                key={i.id}
                className="flex min-w-0 items-center justify-between gap-2 rounded-lg border border-white/10 px-3 py-2"
              >
                <span className="min-w-0 break-words">
                  {i.email}
                  <span className="ml-2 text-xs text-ink-faint">
                    {i.accepted_at ? "accepted" : "pending"}
                  </span>
                </span>
                {!i.accepted_at && (
                  <button
                    type="button"
                    className="btn-ghost text-xs"
                    disabled={busy}
                    onClick={() => void removeInvite(i.id)}
                  >
                    Revoke
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {users.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-faint">Users</h3>
          <ul className="mt-2 space-y-1 text-pretty break-words text-xs text-ink-muted">
            {users.map((u) => (
              <li key={u.email}>
                {u.email} · {u.role}
                {u.tenant_ready ? " · ready" : " · no sheet"}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
