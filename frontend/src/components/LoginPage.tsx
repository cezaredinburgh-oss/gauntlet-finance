import { useAuth } from "../auth/AuthContext";
import { Spinner } from "./Spinner";

export function LoginPage() {
  const { login, loading, error, refresh } = useAuth();

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface px-4">
      <div className="card w-full max-w-md p-8">
        <div className="mb-6">
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-faint">
            Gauntlet Finance
          </div>
          <h1 className="mt-2 text-2xl font-bold tracking-tight">Sign in</h1>
          <p className="mt-2 text-sm text-ink-muted">
            Use the same Google account that owns your spreadsheet (OAuth mode),
            or continue when the API is running in dev auth mode.
          </p>
        </div>

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
