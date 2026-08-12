import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, ApiError, AUTH_UNAUTHORIZED_EVENT } from "../api/client";
import type { AuthMe } from "../api/types";

type AuthState = {
  user: AuthMe | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  login: () => void;
  loginWithPassword: (email: string, password: string) => Promise<void>;
  enterSandbox: () => Promise<void>;
  enterTour: () => Promise<void>;
  logout: () => Promise<void>;
  isDevMode: boolean;
  /** Tour demo: UI should hide write actions (server also 403s). */
  isReadOnly: boolean;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthMe | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const me = await api.me();
      setUser(me);
    } catch (e) {
      setUser(null);
      if (e instanceof ApiError && e.status === 401) {
        setError(null);
      } else if (e instanceof Error) {
        setError(e.message);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onUnauthorized = () => {
      setUser(null);
      setError(null);
      setLoading(false);
    };
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  const login = useCallback(() => {
    window.location.href = api.loginUrl();
  }, []);

  const loginWithPassword = useCallback(async (email: string, password: string) => {
    await api.passwordLogin(email, password);
    const me = await api.me();
    setUser(me);
  }, []);

  const enterSandbox = useCallback(async () => {
    await api.enterDemoSandbox();
    const me = await api.me();
    setUser(me);
  }, []);

  const enterTour = useCallback(async () => {
    await api.enterDemoTour();
    const me = await api.me();
    setUser(me);
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      /* ignore */
    }
    // Stay signed out even if a later remount races; guest cookie blocks open-auth me().
    setUser(null);
    setLoading(false);
    setError(null);
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      error,
      refresh,
      login,
      loginWithPassword,
      enterSandbox,
      enterTour,
      logout,
      isDevMode: user?.auth_mode === "dev" || user?.auth_mode === "disabled",
      isReadOnly: Boolean(user?.read_only || user?.demo_kind === "tour"),
    }),
    [user, loading, error, refresh, login, loginWithPassword, enterSandbox, enterTour, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
