import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, ApiError } from "../api/client";
import type { AuthMe } from "../api/types";

type AuthState = {
  user: AuthMe | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  login: () => void;
  logout: () => Promise<void>;
  isDevMode: boolean;
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

  const login = useCallback(() => {
    // Backend sets httpOnly session cookie after Google OAuth
    window.location.href = api.loginUrl();
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      /* ignore */
    }
    setUser(null);
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      error,
      refresh,
      login,
      logout,
      isDevMode: user?.auth_mode === "dev" || user?.auth_mode === "disabled",
    }),
    [user, loading, error, refresh, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
