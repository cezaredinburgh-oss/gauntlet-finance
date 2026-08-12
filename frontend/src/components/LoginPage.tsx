import { useEffect, useMemo, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { Spinner } from "./Spinner";

function readAuthError(): { code: string | null; email: string | null } {
  try {
    const params = new URLSearchParams(window.location.search);
    return {
      code: params.get("auth_error"),
      email: params.get("email"),
    };
  } catch {
    return { code: null, email: null };
  }
}

function clearAuthErrorFromUrl(): void {
  try {
    const url = new URL(window.location.href);
    if (!url.searchParams.has("auth_error") && !url.searchParams.has("email")) {
      return;
    }
    url.searchParams.delete("auth_error");
    url.searchParams.delete("email");
    window.history.replaceState({}, "", url.pathname + url.search + url.hash);
  } catch {
    /* ignore */
  }
}

export function LoginPage() {
  const { login, loading, error, refresh } = useAuth();
  const initial = useMemo(() => readAuthError(), []);
  const [authError, setAuthError] = useState(initial.code);
  const [authEmail, setAuthEmail] = useState(initial.email);

  useEffect(() => {
    if (initial.code) {
      clearAuthErrorFromUrl();
    }
  }, [initial.code]);

  const notInvited = authError === "not_invited";

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface px-4">
      <div className="card w-full max-w-md p-8">
        <div className="mb-6">
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-faint">
            Gauntlet Finance
          </div>
          <h1 className="mt-2 text-2xl font-bold tracking-tight">Sign in</h1>
          <p className="mt-2 text-sm text-ink-muted">
            {notInvited
              ? "This deployment is invite-only. Your Google account is not on the list."
              : "Use Google to sign in. On multi-tenant hosts only invited accounts can access data."}
          </p>
        </div>

        {notInvited && (
          <div className="mb-4 rounded-xl border border-amber-400/40 bg-amber-400/10 px-3 py-3 text-sm text-amber-100">
            <div className="font-semibold">Not invited</div>
            <p className="mt-1 text-amber-100/90">
              {authEmail ? (
                <>
                  <span className="font-medium text-ink">{authEmail}</span> does not have an
                  invite. Ask a platform admin to invite you, then try again.
                </>
              ) : (
                <>Ask a platform admin to invite your Google email, then try again.</>
              )}
            </p>
            <button
              type="button"
              className="mt-2 text-xs underline text-amber-100/80"
              onClick={() => {
                setAuthError(null);
                setAuthEmail(null);
              }}
            >
              Dismiss
            </button>
          </div>
        )}

        {error && (
          <div className="mb-4 rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
            <button type="button" className="ml-2 underline" onClick={() => void refresh()}>
              Retry
            </button>
          </div>
        )}

        <button
          type="button"
          className="btn-primary w-full"
          onClick={login}
          disabled={loading}
        >
          {loading ? <Spinner /> : null}
          Continue with Google
        </button>

        <p className="mt-4 text-center text-xs text-ink-faint">
          Dev mode: if the backend uses <code className="text-ink-muted">AUTH_MODE=dev</code>,
          refresh — you may already be signed in as the local user.
        </p>
        <button type="button" className="btn-ghost mt-2 w-full text-xs" onClick={() => void refresh()}>
          Check session
        </button>
      </div>
    </div>
  );
}
