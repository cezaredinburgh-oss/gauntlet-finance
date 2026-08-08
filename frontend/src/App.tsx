import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { LoginPage } from "./components/LoginPage";
import { PageLoader } from "./components/Spinner";
import { DashboardPage } from "./pages/DashboardPage";
import { SpendingPage } from "./pages/SpendingPage";
import { CategorizePage } from "./pages/CategorizePage";
import { InvestmentsPage } from "./pages/InvestmentsPage";
import { InvestmentsAnalysisPage } from "./pages/InvestmentsAnalysisPage";
import { TaxPage } from "./pages/TaxPage";
import { AlertsPage } from "./pages/AlertsPage";
import { UploadPage } from "./pages/UploadPage";
import { SettingsPage } from "./pages/SettingsPage";

function Protected({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <PageLoader label="Checking session…" />;
  if (!user) return <LoginPage />;
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
        <Routes>
          <Route
            element={
              <Protected>
                <Layout />
              </Protected>
            }
          >
            <Route index element={<DashboardPage />} />
            <Route path="expenses">
              <Route index element={<Navigate to="spending" replace />} />
              <Route path="spending" element={<SpendingPage />} />
              <Route path="categorize" element={<CategorizePage />} />
              <Route path="alerts" element={<AlertsPage />} />
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
            <Route path="investments" element={<InvestmentsPage />} />
            <Route path="investments/analysis" element={<InvestmentsAnalysisPage />} />
            <Route path="investments/tax" element={<TaxPage />} />
            <Route path="upload" element={<UploadPage />} />
            <Route path="settings" element={<SettingsPage />} />
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
            <Route path="alerts" element={<Navigate to="/expenses/alerts" replace />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
