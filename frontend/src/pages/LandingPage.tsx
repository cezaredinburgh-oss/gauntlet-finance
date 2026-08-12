import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import {
  FileUp,
  LayoutDashboard,
  Shield,
  Sparkles,
  Tags,
  Wallet,
} from "lucide-react";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Spinner } from "../components/Spinner";
import { cn } from "../lib/cn";

const USPS = [
  {
    icon: Shield,
    title: "Your statements. Your sheet.",
    body: "Ledger in a private Google Spreadsheet — not a black-box desk import.",
  },
  {
    icon: LayoutDashboard,
    title: "Executive snapshot",
    body: "Wealth, cash pulse, and alerts first — not a raw spreadsheet dump.",
  },
  {
    icon: Wallet,
    title: "Honest multi-currency",
    body: "USD primary, CZK on hover. Market rates only — we never invent FX.",
  },
  {
    icon: Sparkles,
    title: "Czech tax runway",
    body: "FIFO lots with 3-year (1095-day) exemption tracking.",
  },
  {
    icon: FileUp,
    title: "Banks you use",
    body: "Raiffeisen, Revolut cash/stocks/crypto, eToro — drop exports, we detect format.",
  },
  {
    icon: Tags,
    title: "Spend truth",
    body: "Internal transfers and crypto-pot moves stay out of income/expense.",
  },
] as const;

type PublicConfig = {
  auth_mode: string;
  multi_tenant: boolean;
  demo_login_enabled: boolean;
  demo_email: string | null;
  google_login_available: boolean;
};

function readAuthError(params: URLSearchParams): {
  code: string | null;
  email: string | null;
} {
  return {
    code: params.get("auth_error"),
    email: params.get("email"),
  };
}

export function LandingPage() {
  const { user, loading, login, loginWithPassword, refresh } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const initialErr = useMemo(() => readAuthError(params), [params]);

  const [publicCfg, setPublicCfg] = useState<PublicConfig | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [authError, setAuthError] = useState(initialErr.code);
  const [authEmail, setAuthEmail] = useState(initialErr.email);

  useEffect(() => {
    if (initialErr.code) {
      const next = new URLSearchParams(params);
      next.delete("auth_error");
      next.delete("email");
      setParams(next, { replace: true });
    }
  }, [initialErr.code, params, setParams]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cfg = await api.publicAuthConfig();
        if (!cancelled) {
          setPublicCfg(cfg);
          if (cfg.demo_login_enabled && cfg.demo_email) {
            setEmail(cfg.demo_email);
          }
        }
      } catch {
        if (!cancelled) {
          setPublicCfg({
            auth_mode: "unknown",
            multi_tenant: false,
            demo_login_enabled: false,
            demo_email: null,
            google_login_available: false,
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const onDemoSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setBusy(true);
      setFormError(null);
      try {
        await loginWithPassword(email.trim(), password);
        navigate("/", { replace: true });
      } catch (err) {
        const msg =
          err instanceof ApiError
            ? err.detail
            : err instanceof Error
              ? err.message
              : "Login failed";
        setFormError(msg);
      } finally {
        setBusy(false);
      }
    },
    [email, password, loginWithPassword, navigate],
  );

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface">
        <Spinner className="h-8 w-8" />
      </div>
    );
  }

  if (user) {
    return <Navigate to="/" replace />;
  }

  const demoOn = publicCfg?.demo_login_enabled === true;
  const googleOn = publicCfg?.google_login_available !== false;
  const notInvited = authError === "not_invited";

  return (
    <div className="min-h-screen bg-surface text-ink">
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute -left-24 top-20 h-72 w-72 rounded-full bg-brand/10 blur-3xl" />
        <div className="absolute -right-16 bottom-10 h-80 w-80 rounded-full bg-emerald-400/10 blur-3xl" />
      </div>

      <div className="relative mx-auto grid max-w-6xl gap-10 px-4 py-12 lg:grid-cols-2 lg:items-start lg:py-20">
        <section className="space-y-6">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-faint">
              Gauntlet Finance
            </div>
            <h1 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">
              Your statements. Your sheet. Executive clarity.
            </h1>
            <p className="mt-3 max-w-xl text-sm text-ink-muted sm:text-base">
              Personal multi-currency finance desk: statements-only ledger, private Google
              Sheets storage, executive Home, and Czech tax runway on investments.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            {USPS.map((u) => (
              <div key={u.title} className="card flex gap-3 p-4">
                <div className="rounded-xl bg-brand/15 p-2 text-brand">
                  <u.icon className="h-5 w-5" />
                </div>
                <div>
                  <div className="text-sm font-semibold">{u.title}</div>
                  <p className="mt-1 text-xs text-ink-muted">{u.body}</p>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="card space-y-5 p-6 sm:p-8">
          <div>
            <h2 className="text-xl font-semibold tracking-tight">Sign in</h2>
            <p className="mt-1 text-sm text-ink-muted">
              {publicCfg?.multi_tenant
                ? "Invite-only for Google accounts. Or try the shared demo when enabled."
                : "Sign in with Google, or use the demo account when enabled on this host."}
            </p>
          </div>

          {notInvited && (
            <div className="rounded-xl border border-amber-400/40 bg-amber-400/10 px-3 py-3 text-sm text-amber-100">
              <div className="font-semibold">Not invited</div>
              <p className="mt-1 text-amber-100/90">
                {authEmail ? (
                  <>
                    <span className="font-medium text-ink">{authEmail}</span> is not on the
                    invite list. Ask a platform admin to invite you.
                  </>
                ) : (
                  <>Ask a platform admin to invite your Google email.</>
                )}
              </p>
              <button
                type="button"
                className="mt-2 text-xs underline"
                onClick={() => {
                  setAuthError(null);
                  setAuthEmail(null);
                }}
              >
                Dismiss
              </button>
            </div>
          )}

          {formError && (
            <div className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
              {formError}
            </div>
          )}

          {demoOn && (
            <form className="space-y-3" onSubmit={(e) => void onDemoSubmit(e)}>
              <div className="text-xs font-semibold uppercase tracking-wide text-brand">
                Demo account
              </div>
              <div>
                <label className="label" htmlFor="demo-email">
                  Email
                </label>
                <input
                  id="demo-email"
                  className="input"
                  type="email"
                  autoComplete="username"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
              <div>
                <label className="label" htmlFor="demo-password">
                  Password
                </label>
                <input
                  id="demo-password"
                  className="input"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  placeholder="demo"
                />
              </div>
              <p className="text-xs text-ink-faint">
                Host-configured demo credentials (default password when set:{" "}
                <code className="text-ink-muted">demo</code>). Isolated demo ledger — not your
                real data.
              </p>
              <button type="submit" className="btn-primary w-full" disabled={busy}>
                {busy ? <Spinner className="border-t-slate-900" /> : null}
                Enter demo
              </button>
            </form>
          )}

          {demoOn && googleOn && (
            <div className="flex items-center gap-3 text-xs text-ink-faint">
              <div className="h-px flex-1 bg-white/10" />
              or
              <div className="h-px flex-1 bg-white/10" />
            </div>
          )}

          {googleOn && (
            <div className="space-y-2">
              <button
                type="button"
                className={cn("w-full", demoOn ? "btn-secondary" : "btn-primary")}
                onClick={login}
              >
                Continue with Google
              </button>
              {publicCfg?.multi_tenant && (
                <p className="text-center text-xs text-ink-faint">
                  Platform admins manage invites after signing in with an admin Google account.
                </p>
              )}
            </div>
          )}

          {!demoOn && !googleOn && (
            <p className="text-sm text-ink-muted">
              No login methods are enabled on this host. Set{" "}
              <code className="text-ink">DEMO_LOGIN_ENABLED</code> or{" "}
              <code className="text-ink">AUTH_MODE=oauth</code>.
            </p>
          )}

          <button
            type="button"
            className="btn-ghost w-full text-xs"
            onClick={() => void refresh()}
          >
            Check existing session
          </button>

          <p className="text-center text-xs text-ink-faint">
            Already set up?{" "}
            <Link to="/" className="text-brand hover:underline">
              Open app
            </Link>
          </p>
        </section>
      </div>
    </div>
  );
}
