import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  LineChart,
  Upload,
  Settings,
  RefreshCw,
  LogOut,
  Menu,
  X,
  Bell,
  Tags,
  Wallet,
  ChevronDown,
  Receipt,
  type LucideIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { useAuth } from "../auth/AuthContext";
import { api } from "../api/client";
import type { AlertItem } from "../api/types";
import {
  ALERTS_SEEN_EVENT,
  ALERTS_SEEN_STORAGE_KEY,
  countUnseenAlerts,
  pruneSeenAlertKeys,
} from "../lib/alertSeen";
import { cn } from "../lib/cn";
import { Spinner } from "./Spinner";

type NavLeaf = {
  kind: "leaf";
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  /** Badge key for special treatment (e.g. alerts) */
  badge?: "alerts";
};

type NavGroup = {
  kind: "group";
  id: string;
  label: string;
  icon: LucideIcon;
  /** Default route when the group header is activated */
  defaultTo: string;
  children: NavLeaf[];
};

type NavItem = NavLeaf | NavGroup;

const nav: NavItem[] = [
  { kind: "leaf", to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  {
    kind: "group",
    id: "expenses",
    label: "Expense tracking",
    icon: Wallet,
    defaultTo: "/expenses/spending",
    children: [
      { kind: "leaf", to: "/expenses/spending", label: "Spending", icon: Wallet },
      { kind: "leaf", to: "/expenses/categorize", label: "Categorize", icon: Tags },
      { kind: "leaf", to: "/expenses/alerts", label: "Alerts", icon: Bell, badge: "alerts" },
    ],
  },
  {
    kind: "group",
    id: "investments",
    label: "Investments",
    icon: LineChart,
    defaultTo: "/investments",
    children: [
      { kind: "leaf", to: "/investments", label: "Holdings", icon: LineChart, end: true },
      { kind: "leaf", to: "/investments/analysis", label: "Analysis", icon: LineChart },
      { kind: "leaf", to: "/investments/dca", label: "DCA", icon: LineChart },
      { kind: "leaf", to: "/investments/tax", label: "Tax", icon: Receipt },
    ],
  },
  { kind: "leaf", to: "/upload", label: "Upload", icon: Upload },
  { kind: "leaf", to: "/settings", label: "Settings", icon: Settings },
];

/** Primary destinations for the mobile bottom bar */
const mobileBottom: Array<{
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  matchPrefix?: string;
}> = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  {
    to: "/expenses/spending",
    label: "Expenses",
    icon: Wallet,
    matchPrefix: "/expenses",
  },
  { to: "/investments", label: "Investments", icon: LineChart },
  { to: "/upload", label: "Upload", icon: Upload },
  { to: "/settings", label: "Settings", icon: Settings },
];

const EXPENSES_OPEN_KEY = "nav.expenses.open";
const INVESTMENTS_OPEN_KEY = "nav.investments.open";

function pathInGroup(pathname: string, group: NavGroup): boolean {
  return group.children.some(
    (c) => pathname === c.to || pathname.startsWith(c.to + "/"),
  );
}

function leafActiveClass(isActive: boolean): string {
  return cn(
    "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition",
    isActive
      ? "bg-brand/15 text-brand"
      : "text-ink-muted hover:bg-white/5 hover:text-ink",
  );
}

/** Stable sidebar/drawer nav (not recreated inside Layout each render). */
function NavItems({
  pathname,
  expensesOpen,
  investmentsOpen,
  setExpensesOpen,
  setInvestmentsOpen,
  alertBadge,
  onNavigate,
  navigate,
}: {
  pathname: string;
  expensesOpen: boolean;
  investmentsOpen: boolean;
  setExpensesOpen: Dispatch<SetStateAction<boolean>>;
  setInvestmentsOpen: Dispatch<SetStateAction<boolean>>;
  /** Unseen active alerts (all levels); only on Alerts leaf, not group header */
  alertBadge: number;
  onNavigate?: () => void;
  navigate: (to: string) => void;
}) {
  function renderLeaf(
    leaf: NavLeaf,
    opts: { onNavigate?: () => void; nested?: boolean } = {},
  ) {
    const Icon = leaf.icon;
    return (
      <NavLink
        key={leaf.to}
        to={leaf.to}
        end={leaf.end}
        onClick={opts.onNavigate}
        className={({ isActive }) =>
          cn(leafActiveClass(isActive), opts.nested && "py-2 pl-3")
        }
      >
        <Icon className={cn("shrink-0", opts.nested ? "h-4 w-4" : "h-5 w-5")} />
        <span className="flex-1">{leaf.label}</span>
        {leaf.badge === "alerts" && alertBadge > 0 && (
          <span className="badge bg-warn/20 text-warn">{alertBadge}</span>
        )}
      </NavLink>
    );
  }

  return (
    <nav className="flex flex-col gap-1 p-3">
      {nav.map((item) => {
        if (item.kind === "leaf") {
          return renderLeaf(item, { onNavigate });
        }

        const GroupIcon = item.icon;
        const open =
          item.id === "expenses"
            ? expensesOpen
            : item.id === "investments"
              ? investmentsOpen
              : true;
        const groupActive = pathInGroup(pathname, item);

        return (
          <div key={item.id} className="space-y-0.5">
            <div
              className={cn(
                "flex items-center gap-1 rounded-xl transition",
                groupActive && !open
                  ? "bg-brand/15 text-brand"
                  : groupActive
                    ? "text-brand"
                    : "text-ink-muted",
              )}
            >
              <button
                type="button"
                className={cn(
                  "flex min-w-0 flex-1 items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-medium transition hover:bg-white/5 hover:text-ink",
                  groupActive && "text-brand",
                )}
                onClick={() => {
                  if (item.id === "expenses") setExpensesOpen(true);
                  if (item.id === "investments") setInvestmentsOpen(true);
                  navigate(item.defaultTo);
                  onNavigate?.();
                }}
              >
                <GroupIcon className="h-5 w-5 shrink-0" />
                <span className="flex-1 truncate">{item.label}</span>
                {/* Collapsed expenses: non-numeric hint (leaf holds the count when open). */}
                {item.id === "expenses" && !open && alertBadge > 0 && (
                  <span
                    className="h-1.5 w-1.5 shrink-0 rounded-full bg-warn"
                    title={`${alertBadge} unseen alert${alertBadge === 1 ? "" : "s"}`}
                    aria-hidden
                  />
                )}
              </button>
              <button
                type="button"
                className="rounded-lg p-2 text-ink-muted hover:bg-white/5 hover:text-ink"
                aria-label={open ? `Collapse ${item.label}` : `Expand ${item.label}`}
                aria-expanded={open}
                onClick={() => {
                  if (item.id === "expenses") setExpensesOpen((v) => !v);
                  if (item.id === "investments") setInvestmentsOpen((v) => !v);
                }}
              >
                <ChevronDown
                  className={cn(
                    "h-4 w-4 transition-transform",
                    open ? "rotate-0" : "-rotate-90",
                  )}
                />
              </button>
            </div>
            {open && (
              <div className="ml-3 space-y-0.5 border-l border-white/10 pl-2">
                {item.children.map((child) =>
                  renderLeaf(child, { onNavigate, nested: true }),
                )}
              </div>
            )}
          </div>
        );
      })}
    </nav>
  );
}

export function Layout() {
  const { user, logout, isDevMode } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [priceBusy, setPriceBusy] = useState(false);
  const [priceMsg, setPriceMsg] = useState<string | null>(null);
  const [alertBadge, setAlertBadge] = useState(0);
  /** Always-current inventory for event-driven badge recompute (avoids empty-state race). */
  const alertItemsRef = useRef<AlertItem[]>([]);

  const expensesGroup = useMemo(
    () => nav.find((n): n is NavGroup => n.kind === "group" && n.id === "expenses")!,
    [],
  );
  const investmentsGroup = useMemo(
    () => nav.find((n): n is NavGroup => n.kind === "group" && n.id === "investments")!,
    [],
  );
  const expensesActive = pathInGroup(location.pathname, expensesGroup);
  const investmentsActive = pathInGroup(location.pathname, investmentsGroup);

  const [expensesOpen, setExpensesOpen] = useState(() => {
    if (typeof window === "undefined") return true;
    if (window.location.pathname.startsWith("/expenses")) return true;
    try {
      const stored = sessionStorage.getItem(EXPENSES_OPEN_KEY);
      if (stored === "0") return false;
      if (stored === "1") return true;
    } catch {
      /* ignore */
    }
    return true;
  });
  const [investmentsOpen, setInvestmentsOpen] = useState(() => {
    if (typeof window === "undefined") return true;
    if (window.location.pathname.startsWith("/investments")) return true;
    try {
      const stored = sessionStorage.getItem(INVESTMENTS_OPEN_KEY);
      if (stored === "0") return false;
      if (stored === "1") return true;
    } catch {
      /* ignore */
    }
    return true;
  });

  useEffect(() => {
    if (expensesActive && !expensesOpen) setExpensesOpen(true);
  }, [expensesActive, expensesOpen]);
  useEffect(() => {
    if (investmentsActive && !investmentsOpen) setInvestmentsOpen(true);
  }, [investmentsActive, investmentsOpen]);

  useEffect(() => {
    try {
      sessionStorage.setItem(EXPENSES_OPEN_KEY, expensesOpen ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [expensesOpen]);
  useEffect(() => {
    try {
      sessionStorage.setItem(INVESTMENTS_OPEN_KEY, investmentsOpen ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [investmentsOpen]);

  const applyAlertItems = useCallback((items: AlertItem[]) => {
    pruneSeenAlertKeys(items);
    alertItemsRef.current = items;
    setAlertBadge(countUnseenAlerts(items));
  }, []);

  const fetchAlertBadge = useCallback(async () => {
    try {
      const r = await api.alerts();
      applyAlertItems(r.items ?? []);
    } catch {
      /* ignore badge errors */
    }
  }, [applyAlertItems]);

  useEffect(() => {
    let cancelled = false;
    // Defer first badge fetch so it doesn't race the dashboard's Sheets load
    const t = window.setTimeout(() => {
      if (!cancelled) void fetchAlertBadge();
    }, 750);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [fetchAlertBadge]);

  // Refresh inventory when visiting Alerts (page has its own fetch; keep badge in sync).
  useEffect(() => {
    if (location.pathname.startsWith("/expenses/alerts")) {
      void fetchAlertBadge();
    }
  }, [location.pathname, fetchAlertBadge]);

  // Soft refresh when the tab becomes visible again (imports / other tabs).
  useEffect(() => {
    function onVis() {
      if (document.visibilityState === "visible") void fetchAlertBadge();
    }
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [fetchAlertBadge]);

  // Recompute from ref when Alerts page marks seen (same tab) or storage changes (other tabs).
  useEffect(() => {
    function refreshBadge() {
      setAlertBadge(countUnseenAlerts(alertItemsRef.current));
    }
    function onStorage(e: StorageEvent) {
      if (e.key === ALERTS_SEEN_STORAGE_KEY || e.key === null) refreshBadge();
    }
    window.addEventListener(ALERTS_SEEN_EVENT, refreshBadge);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(ALERTS_SEEN_EVENT, refreshBadge);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  /**
   * Soft live marks (~60s) on Dashboard + Investments so portfolio MV tracks
   * the same cadence as 1D charts. Uses force=false (server quote TTL).
   * Skips when tab hidden or a manual refresh is in flight.
   */
  useEffect(() => {
    const path = location.pathname;
    const wealth =
      path === "/" ||
      path === "/dashboard" ||
      path.startsWith("/investments");
    if (!wealth) return;

    let busy = false;
    const tick = async () => {
      if (busy) return;
      if (typeof document !== "undefined" && document.visibilityState === "hidden") {
        return;
      }
      busy = true;
      try {
        const r = await api.refreshPrices(false);
        window.dispatchEvent(
          new CustomEvent("prices-updated", {
            detail: { quote_count: r.quote_count, as_of: r.as_of, soft: true },
          }),
        );
      } catch {
        /* quiet — manual Update prices still available */
      } finally {
        busy = false;
      }
    };

    const id = window.setInterval(() => void tick(), 60_000);
    const onVis = () => {
      if (document.visibilityState === "visible") void tick();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [location.pathname]);

  async function refreshPrices() {
    setPriceBusy(true);
    setPriceMsg(null);
    try {
      const r = await api.refreshPrices(true);
      setPriceMsg(
        r.quote_count
          ? `Updated ${r.quote_count} quote${r.quote_count === 1 ? "" : "s"}`
          : r.errors?.[0] || "No quotes returned",
      );
      // Let open pages (Investments digests, dashboard) refetch mark-to-market data
      window.dispatchEvent(
        new CustomEvent("prices-updated", {
          detail: { quote_count: r.quote_count, as_of: r.as_of },
        }),
      );
    } catch (e) {
      setPriceMsg(e instanceof Error ? e.message : "Price refresh failed");
    } finally {
      setPriceBusy(false);
      setTimeout(() => setPriceMsg(null), 4000);
    }
  }

  return (
    <div className="min-h-screen bg-surface text-ink lg:flex">
      {/* Desktop sidebar — sticky so it stays visible while main scrolls */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-slate-500/20 bg-surface-raised/95 backdrop-blur-md lg:sticky lg:top-0 lg:flex lg:h-screen lg:max-h-screen">
        <div className="safe-top border-b border-slate-500/20 px-4 py-5">
          <Link to="/" className="block rounded-lg outline-none ring-brand/40 focus-visible:ring-2">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-ink-faint">
              Gauntlet
            </div>
            <div className="text-lg font-bold tracking-tight">Finance</div>
          </Link>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <NavItems
            pathname={location.pathname}
            expensesOpen={expensesOpen}
            investmentsOpen={investmentsOpen}
            setExpensesOpen={setExpensesOpen}
            setInvestmentsOpen={setInvestmentsOpen}
            alertBadge={alertBadge}
            navigate={navigate}
          />
        </div>
        <div className="border-t border-slate-500/20 p-4 text-xs text-ink-muted">
          <div className="truncate font-medium text-ink">{user?.name || user?.email}</div>
          <div className="truncate">{user?.email}</div>
          {isDevMode && (
            <div className="mt-1 badge bg-warn/15 text-warn">Dev auth</div>
          )}
          <button
            type="button"
            onClick={() => void logout()}
            className="btn-ghost mt-2 w-full justify-start px-0 text-xs"
          >
            <LogOut className="h-3.5 w-3.5" /> Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex min-w-0 flex-1 flex-col pb-20 lg:pb-0">
        <header className="safe-top sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-white/5 bg-surface/90 px-4 py-3 backdrop-blur-md">
          <div className="flex items-center gap-2 lg:hidden">
            <button
              type="button"
              className="btn-ghost p-2"
              onClick={() => setMobileOpen(true)}
              aria-label="Open menu"
            >
              <Menu className="h-5 w-5" />
            </button>
            <Link to="/" className="font-semibold">
              Gauntlet
            </Link>
          </div>
          <div className="hidden text-sm text-ink-muted lg:block">
            Personal finance · USD primary
          </div>
          <div className="flex items-center gap-2">
            {priceMsg && (
              <span className="hidden max-w-[12rem] truncate text-xs text-ink-muted sm:inline">
                {priceMsg}
              </span>
            )}
            <button
              type="button"
              className="btn-primary"
              onClick={() => void refreshPrices()}
              disabled={priceBusy}
            >
              {priceBusy ? <Spinner className="h-4 w-4 border-t-slate-900" /> : <RefreshCw className="h-4 w-4" />}
              <span className="hidden sm:inline">Update prices</span>
              <span className="sm:hidden">Prices</span>
            </button>
          </div>
        </header>

        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-5 sm:px-6">
          <Outlet />
        </main>
      </div>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-black/60"
            aria-label="Close menu"
            onClick={() => setMobileOpen(false)}
          />
          <div className="absolute inset-y-0 left-0 flex w-72 flex-col bg-surface-raised shadow-card">
            <div className="flex items-center justify-between border-b border-white/5 px-4 py-4">
              <span className="font-semibold">Menu</span>
              <button type="button" className="btn-ghost p-2" onClick={() => setMobileOpen(false)}>
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto">
              <NavItems
                pathname={location.pathname}
                expensesOpen={expensesOpen}
                investmentsOpen={investmentsOpen}
                setExpensesOpen={setExpensesOpen}
                setInvestmentsOpen={setInvestmentsOpen}
                alertBadge={alertBadge}
                navigate={navigate}
                onNavigate={() => setMobileOpen(false)}
              />
            </div>
          </div>
        </div>
      )}

      {/* Mobile bottom nav — primary destinations */}
      <nav className="safe-bottom fixed inset-x-0 bottom-0 z-40 border-t border-white/5 bg-surface-raised/95 backdrop-blur-md lg:hidden">
        <div className="mx-auto grid max-w-lg grid-cols-5 gap-0 px-1 pt-1">
          {mobileBottom.map(({ to, label, icon: Icon, end, matchPrefix }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) => {
                const active =
                  isActive ||
                  (matchPrefix != null && location.pathname.startsWith(matchPrefix));
                return cn(
                  "relative flex flex-col items-center gap-0.5 rounded-lg px-1 py-2 text-[10px] font-medium",
                  active ? "text-brand" : "text-ink-faint",
                );
              }}
            >
              <Icon className="h-5 w-5" />
              {matchPrefix === "/expenses" && alertBadge > 0 && (
                <span className="absolute right-2 top-1 h-1.5 w-1.5 rounded-full bg-warn" />
              )}
              {label.split(" ")[0]}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}
