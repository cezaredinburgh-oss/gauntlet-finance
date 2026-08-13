import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
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
import { resetDemoOnboarding } from "../lib/onboarding";

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
  demo_sandbox_enabled?: boolean;
  demo_tour_enabled?: boolean;
  lab_login_enabled?: boolean;
  owner_login_enabled?: boolean;
  google_login_available: boolean;
  open_auth?: boolean;
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
  const { user, loading, login, loginWithPassword, enterSandbox, enterTour, logout, refresh } =
    useAuth();
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
          // Owner email is not exposed publicly — user types their own.
        }
      } catch {
        if (!cancelled) {
          setPublicCfg({
            auth_mode: "unknown",
            multi_tenant: false,
            demo_login_enabled: false,
            demo_email: null,
            demo_sandbox_enabled: false,
            demo_tour_enabled: false,
            lab_login_enabled: false,
            google_login_available: false,
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const onOneClick = useCallback(
    async (kind: "tour" | "sandbox") => {
      setBusy(true);
      setFormError(null);
      try {
        if (kind === "tour") await enterTour();
        else await enterSandbox();
        resetDemoOnboarding(kind);
        navigate("/onboarding", { replace: true });
      } catch (err) {
        const msg =
          err instanceof ApiError
            ? err.detail
            : err instanceof Error
              ? err.message
              : "Could not start demo";
        setFormError(msg);
      } finally {
        setBusy(false);
      }
    },
    [enterTour, enterSandbox, navigate],
  );

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

  if (loading && !publicCfg) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface">
        <Spinner className="h-8 w-8" />
      </div>
    );
  }

  const demoOn = publicCfg?.demo_login_enabled === true;
  const tourOn = publicCfg?.demo_tour_enabled === true;
  const sandboxOn = publicCfg?.demo_sandbox_enabled === true;
  const oneClickOn = tourOn || sandboxOn;
  const ownerOn = publicCfg?.owner_login_enabled === true;
  const labOn = publicCfg?.lab_login_enabled === true;
  const passwordOn = demoOn || ownerOn || labOn;
  const googleOn = publicCfg?.google_login_available === true;
  const notInvited = authError === "not_invited";
  /** Only when host allows unauthenticated full access (dangerous on public URLs). */
  const openAuth = publicCfg?.open_auth === true;
  const signedIn = Boolean(user);

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

        <div className="space-y-4">
          {/* —— Account sign-in (real users / owner) —— */}
          <section className="card space-y-5 p-6 sm:p-8">
            <div>
              <h2 className="text-xl font-semibold tracking-tight">
                {signedIn ? "You're signed in" : "Sign in to your account"}
              </h2>
              <p className="mt-1 text-sm text-ink-muted">
                {signedIn
                  ? "Open the app, or sign out to use another account or try a public demo."
                  : publicCfg?.multi_tenant
                    ? "Invite-only Google accounts and host-configured password logins."
                    : "Use Google or your host email/password — this is your real ledger, not a demo."}
              </p>
            </div>

            {signedIn && (
              <div className="space-y-3 rounded-xl border border-brand/30 bg-brand/10 px-4 py-3 text-sm">
                <div>
                  <div className="font-medium text-ink">{user?.name || "Signed in"}</div>
                  <div className="text-ink-muted">{user?.email}</div>
                  {user?.is_demo && (
                    <div className="mt-1 text-xs text-amber-200">
                      {user.demo_kind === "tour"
                        ? "Sample portfolio (read-only demo)"
                        : "Sandbox demo session"}
                    </div>
                  )}
                  {openAuth && !user?.is_demo && (
                    <div className="mt-1 text-xs text-amber-200">
                      This host allows open access (auto sign-in). Turn off ALLOW_OPEN_AUTH on
                      public domains.
                    </div>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Link to="/" className="btn-primary">
                    Open app
                  </Link>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => {
                      void (async () => {
                        await logout();
                      })();
                    }}
                  >
                    Sign out
                  </button>
                </div>
              </div>
            )}

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

            {!signedIn && passwordOn && (
              <form className="space-y-3" onSubmit={(e) => void onDemoSubmit(e)}>
                <div className="text-xs font-semibold uppercase tracking-wide text-brand">
                  Email &amp; password
                </div>
                <div>
                  <label className="label" htmlFor="account-email">
                    Email
                  </label>
                  <input
                    id="account-email"
                    className="input"
                    type="email"
                    autoComplete="username"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </div>
                <div>
                  <label className="label" htmlFor="account-password">
                    Password
                  </label>
                  <input
                    id="account-password"
                    className="input"
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                </div>
                <ul className="space-y-1 text-xs text-ink-faint">
                  {ownerOn && (
                    <li>
                      <strong className="text-ink-muted">Owner:</strong> private host password
                      — full real data (do not share).
                    </li>
                  )}
                  {demoOn && (
                    <li>
                      <strong className="text-ink-muted">Legacy password demo:</strong>{" "}
                      {publicCfg?.demo_email || "demo@gauntlet.local"} — prefer the one-click
                      demos below when enabled.
                    </li>
                  )}
                  {labOn && (
                    <li>
                      <strong className="text-ink-muted">Lab account:</strong> host-configured
                      test login — full app on a persistent disk ledger (not Sheets).
                    </li>
                  )}
                </ul>
                <button type="submit" className="btn-primary w-full" disabled={busy}>
                  {busy ? <Spinner className="border-t-slate-900" /> : null}
                  Sign in
                </button>
              </form>
            )}

            {!signedIn && passwordOn && googleOn && (
              <div className="flex items-center gap-3 text-xs text-ink-faint">
                <div className="h-px flex-1 bg-white/10" />
                or
                <div className="h-px flex-1 bg-white/10" />
              </div>
            )}

            {!signedIn && googleOn && (
              <button
                type="button"
                className={cn("w-full", passwordOn ? "btn-secondary" : "btn-primary")}
                onClick={login}
              >
                Continue with Google
              </button>
            )}

            {!signedIn && !passwordOn && !googleOn && !oneClickOn && (
              <p className="text-sm text-ink-muted">
                No login methods are enabled on this host. Ask the operator to configure Google
                OAuth or password login.
              </p>
            )}

            {!signedIn && openAuth && (
              <button
                type="button"
                className="btn-secondary w-full text-sm"
                onClick={() => {
                  void (async () => {
                    try {
                      await api.resumeLocalDev();
                      await refresh();
                      navigate("/", { replace: true });
                    } catch (err) {
                      setFormError(
                        err instanceof Error ? err.message : "Could not resume local dev",
                      );
                    }
                  })();
                }}
              >
                Continue as local dev user (open access)
              </button>
            )}

            {!signedIn && (
              <button
                type="button"
                className="btn-ghost w-full text-xs"
                onClick={() => void refresh()}
              >
                Check existing session
              </button>
            )}
          </section>

          {/* —— Public demos (separate product surface) —— */}
          {!signedIn && oneClickOn && (
            <section className="card space-y-4 border border-sky-400/25 p-6 sm:p-8">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-sky-300/90">
                  Public demos
                </p>
                <h2 className="mt-1 text-lg font-semibold tracking-tight">
                  Try Gauntlet without an account
                </h2>
                <p className="mt-1 text-sm text-ink-muted">
                  Not your real finances. One-click sessions — separate from sign-in above.
                </p>
              </div>

              <div className="space-y-3">
                {tourOn && (
                  <div className="space-y-2">
                    <button
                      type="button"
                      className="btn-primary w-full"
                      disabled={busy}
                      onClick={() => void onOneClick("tour")}
                    >
                      {busy ? <Spinner className="border-t-slate-900" /> : null}
                      Explore sample portfolio
                    </button>
                    <p className="text-xs text-ink-faint">
                      Guided setup walkthrough, then a read-only sample with multi-bank spend and
                      investments.
                    </p>
                  </div>
                )}
                {sandboxOn && (
                  <div className="space-y-2">
                    <button
                      type="button"
                      className={cn("w-full", tourOn ? "btn-secondary" : "btn-primary")}
                      disabled={busy}
                      onClick={() => void onOneClick("sandbox")}
                    >
                      {busy ? <Spinner /> : null}
                      Try with your statements
                    </button>
                    <p className="text-xs text-ink-faint">
                      Empty temporary sandbox — upload statements, try rules; wiped when you sign
                      out.
                    </p>
                  </div>
                )}
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
