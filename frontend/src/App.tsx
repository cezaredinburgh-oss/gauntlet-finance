import { useEffect } from "react";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { PageLoader } from "./components/Spinner";
import { DashboardPage } from "./pages/DashboardPage";
import { NewEtSpendingPageGate } from "./pages/NewEtSpendingPageGate";
import { NewEtCategorizePageGate } from "./pages/NewEtCategorizePageGate";
import { InvestmentsPageGate } from "./pages/InvestmentsPageGate";
import { InvestmentsAnalysisPageGate } from "./pages/InvestmentsAnalysisPageGate";
import { InvestmentsDcaPageGate } from "./pages/InvestmentsDcaPageGate";
import { TaxPageGate } from "./pages/TaxPageGate";
import { AlertsPageGate } from "./pages/AlertsPageGate";
import { UploadPageGate } from "./pages/UploadPageGate";
import { SettingsPageGate } from "./pages/SettingsPageGate";
import { ChartPopoutPage } from "./pages/ChartPopoutPage";
import { OnboardingPage } from "./pages/OnboardingPage";
import { LandingPage } from "./pages/LandingPage";
import { shouldForceDemoOnboarding } from "./lib/onboarding";

const SESSION_BOOT_KEY = "gauntlet.session_boot";

/**
 * Prefer Dashboard on cold open.
 *
 * iOS "Add to Home Screen" and browser restore often reopen the last URL
 * (frequently /settings after deploy/setup). Force home once per tab session
 * so the app feels like it starts on the executive dashboard. In-session
 * visits to Settings still work.
 */
function PreferDashboardOnLaunch() {
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    try {
      if (sessionStorage.getItem(SESSION_BOOT_KEY)) return;
      sessionStorage.setItem(SESSION_BOOT_KEY, "1");
    } catch {
      /* private mode / blocked storage — still try to home from settings */
    }
    if (location.pathname === "/settings") {
      navigate("/", { replace: true });
    }
  }, [location.pathname, navigate]);

  return null;
}

function Protected({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <PageLoader label="Checking session…" />;
  if (!user) {
    const next = `${location.pathname}${location.search}`;
    const q =
      next && next !== "/"
        ? `?next=${encodeURIComponent(next)}`
        : "";
    return <Navigate to={`/login${q}`} replace />;
  }
  // Public demos must finish (or skip sandbox) onboarding before using the app.
  const forceDemo = shouldForceDemoOnboarding({
    isDemo: user.is_demo,
    demoKind: user.demo_kind,
  });
  const onOnboarding = location.pathname === "/onboarding";
  const onSettings = location.pathname === "/settings";
  if (forceDemo && !onOnboarding && !onSettings) {
    return <Navigate to="/onboarding" replace />;
  }
  return <>{children}</>;
}

/** Preserve query string when bouncing legacy routes to Categorize. */
function RedirectPreserveSearch({
  to,
  extraParams,
}: {
  to: string;
  extraParams?: Record<string, string>;
}) {
  const { search } = useLocation();
  const params = new URLSearchParams(search);
  if (extraParams) {
    for (const [k, v] of Object.entries(extraParams)) {
      if (!params.has(k)) params.set(k, v);
    }
  }
  const q = params.toString();
  return <Navigate to={`${to}${q ? `?${q}` : ""}`} replace />;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <PreferDashboardOnLaunch />
        <Routes>
          <Route path="login" element={<LandingPage />} />
          {/* Chart-only pop-out window (no app chrome) */}
          <Route
            path="investments/chart"
            element={
              <Protected>
                <ChartPopoutPage />
              </Protected>
            }
          />
          <Route
            element={
              <Protected>
                <Layout />
              </Protected>
            }
          >
            <Route index element={<DashboardPage />} />
            <Route path="dashboard" element={<Navigate to="/" replace />} />
            <Route path="expenses">
              <Route index element={<Navigate to="spending" replace />} />
              <Route path="spending" element={<NewEtSpendingPageGate />} />
              <Route path="categorize" element={<NewEtCategorizePageGate />} />
              <Route
                path="alerts"
                element={<Navigate to="/alerts" replace />}
              />
              {/* Legacy expense sub-routes */}
              <Route
                path="transactions"
                element={<RedirectPreserveSearch to="/expenses/categorize" />}
              />
              <Route
                path="categories"
                element={
                  <RedirectPreserveSearch
                    to="/expenses/categorize"
                    extraParams={{ panel: "rules" }}
                  />
                }
              />
            </Route>
            <Route path="new-et">
              <Route index element={<Navigate to="/expenses/spending" replace />} />
              <Route
                path="spending"
                element={<RedirectPreserveSearch to="/expenses/spending" />}
              />
              <Route
                path="categorize"
                element={<RedirectPreserveSearch to="/expenses/categorize" />}
              />
            </Route>
            <Route path="investments" element={<InvestmentsPageGate />} />
            <Route path="investments/analysis" element={<InvestmentsAnalysisPageGate />} />
            <Route path="investments/dca" element={<InvestmentsDcaPageGate />} />
            <Route path="investments/tax" element={<TaxPageGate />} />
            <Route path="upload" element={<UploadPageGate />} />
            <Route path="onboarding" element={<OnboardingPage />} />
            <Route path="settings" element={<SettingsPageGate />} />
            <Route path="transactions" element={<RedirectPreserveSearch to="/expenses/categorize" />} />
            <Route
              path="categories"
              element={
                <RedirectPreserveSearch
                  to="/expenses/categorize"
                  extraParams={{ panel: "rules" }}
                />
              }
            />
            <Route path="alerts" element={<AlertsPageGate />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
