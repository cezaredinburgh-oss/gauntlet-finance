export type AuthMe = {
  email: string;
  name: string | null;
  picture: string | null;
  auth_mode: "dev" | "oauth" | "disabled" | string;
  multi_tenant?: boolean;
  user_id?: string | null;
  role?: string | null;
  tenant_ready?: boolean;
  spreadsheet_bound?: boolean;
  is_demo?: boolean;
  demo_login_enabled?: boolean;
};

export type PublicAuthConfig = {
  auth_mode: string;
  multi_tenant: boolean;
  demo_login_enabled: boolean;
  demo_email: string | null;
  google_login_available: boolean;
  open_auth?: boolean;
};

export type Health = {
  status: string;
  app: string;
  auth_mode: string;
  spreadsheet_configured: boolean;
  multi_tenant?: boolean;
};

export type SheetsStatus = {
  backend: string;
  spreadsheet_id?: string | null;
  service_account_email?: string | null;
  tabs?: string[];
  ok?: boolean;
  message?: string;
};

export type CleanupScopePreview = {
  id: string;
  label: string;
  description: string;
  tabs: string[];
  row_counts: Record<string, number>;
  total_rows: number;
  notes?: string;
};

export type CleanupPreview = {
  scopes: CleanupScopePreview[];
  tab_counts: Record<string, number>;
  confirm_token: string;
};

export type CleanupResult = {
  scopes_requested: string[];
  scopes_applied: string[];
  tabs_cleared: Record<string, number>;
  transactions_uncategorized: number;
  message: string;
};

export type Transaction = {
  id: string;
  account_id: string;
  booking_date: string;
  value_date?: string | null;
  amount: string;
  currency: string;
  amount_czk?: string | null;
  amount_usd?: string | null;
  fee_amount: string;
  fee_currency?: string | null;
  merchant?: string | null;
  description?: string | null;
  original_description?: string | null;
  counterparty_name?: string | null;
  source_institution: string;
  external_id?: string | null;
  category_id?: string | null;
  category_override: boolean;
  is_internal_transfer: boolean;
  transfer_group_id?: string | null;
  notes?: string | null;
};

export type Category = {
  id: string;
  name: string;
  parent_id?: string | null;
  necessity: string;
  life_domain: string;
  is_income: boolean;
  is_transfer: boolean;
  sort_order: number;
};

export type Lot = {
  id: string;
  account_id: string;
  ticker: string;
  asset_class: string;
  source: string;
  acquisition_date: string;
  quantity_opened: string;
  quantity_remaining: string;
  cost_basis_native: string;
  cost_basis_czk: string;
  cost_basis_usd: string;
  native_currency: string;
  status: string;
  holding_period_days?: number;
  tax_free_on?: string;
  qualifies_3y_exemption?: boolean;
};

export type LotSummary = {
  ticker: string;
  total_quantity: string;
  quantity_tax_free: string;
  quantity_pending: string;
  cost_basis_native: string;
  cost_basis_czk: string;
  cost_basis_usd: string;
  native_currency: string | null;
  as_of?: string;
  lots: Array<{
    lot_id: string;
    ticker: string;
    quantity_remaining: string;
    acquisition_date: string;
    tax_free_on: string;
    holding_period_days: number;
    qualifies_3y_exemption: boolean;
    cost_basis_native: string;
    cost_basis_czk: string;
    cost_basis_usd: string;
    native_currency: string;
  }>;
};

export type TopItem = {
  label: string;
  amount_usd: string;
  count: number;
};

export type CurrencyRow = {
  currency: string;
  income: string;
  expense: string;
  net: string;
};

export type DashboardSummary = {
  filters: {
    date_from: string | null;
    date_to: string | null;
    currency: string | null;
    period_key?: string | null;
  };
  cashflow: {
    transaction_count: number;
    internal_transfer_count: number;
    income: string;
    expense: string;
    net: string;
    income_usd: string;
    expense_usd: string;
    net_usd: string;
    income_czk: string;
    expense_czk: string;
    net_czk: string;
    by_currency: CurrencyRow[];
    top_income: TopItem[];
    top_expense_merchants: TopItem[];
    top_expense_domains: TopItem[];
    unconverted_count: number;
    expense_by_currency: Record<string, string>;
  };
  comparison: {
    prior_from: string | null;
    prior_to: string | null;
    income_usd: string;
    expense_usd: string;
    net_usd: string;
    income_change_pct: number | null;
    expense_change_pct: number | null;
    net_change_pct: number | null;
  } | null;
  pace: {
    spend_30d_usd: string;
    spend_30d_investments_usd?: string;
    spend_30d_living_usd?: string;
    avg_monthly_6m_usd: string;
    avg_monthly_6m_investments_usd?: string;
    avg_monthly_6m_living_usd?: string;
    pace_pct: number | null;
    pace_pct_living?: number | null;
    investments_share_30d_pct?: number | null;
    investments_share_6m_avg_pct?: number | null;
  };
  spending: {
    by_domain: Array<{ name: string; amount_usd: string }>;
    by_necessity: Array<{ name: string; amount_usd: string }>;
    by_category?: Array<{
      id: string;
      name: string;
      amount_usd: string;
      life_domain: string;
      necessity: string;
      pct_of_spend: number;
    }>;
    uncategorized_expense_usd: string;
    uncategorized_pct: number;
  };
  portfolio: {
    ticker_count: number;
    positions_with_tax_free_qty: number;
    total_cost_basis_usd: string;
    total_cost_basis_czk?: string;
    total_market_value: string | null;
    unrealized_usd?: string | null;
    unrealized_pct?: number | null;
    tax_free_now_usd?: string;
    prices_as_of?: string | null;
    top_tickers_by_cost?: Array<{
      ticker: string;
      cost_usd: string;
      market_value_usd: string | null;
    }>;
    positions: Array<{
      ticker: string;
      quantity: string;
      quantity_tax_free: string;
      quantity_pending: string;
      cost_basis_usd: string;
      price: string | null;
      market_value: string | null;
    }>;
  };
  portfolio_compact: {
    total_cost_basis_usd: string;
    total_cost_basis_czk?: string;
    total_market_value_usd: string | null;
    unrealized_usd: string | null;
    unrealized_pct: number | null;
    tax_free_now_usd: string;
    ticker_count: number;
    prices_as_of: string | null;
    top_tickers_by_cost: Array<{
      ticker: string;
      cost_usd: string;
      market_value_usd: string | null;
    }>;
    living_draw_12m?: LivingDraw12m | null;
    health?: { grade: string; score: number; summary: string } | null;
    price_status?: {
      mode: string;
      note: string;
      mode_note?: string;
      prices_as_of?: string | null;
    } | null;
  };
};

export type AlertLevel = "info" | "warn" | "danger" | "opportunity";

export type AlertItem = {
  id: string;
  level: AlertLevel | string;
  title: string;
  body: string;
  href?: string | null;
  /** Optional domain hint from API (spending | stocks | crypto) */
  domain?: string | null;
};

export type AlertsResponse = {
  items: AlertItem[];
  warn_count: number;
  total: number;
};

export type DcaOpportunityItem = {
  ticker: string;
  asset_class: string;
  score: number;
  eligible: boolean;
  level: "info" | "warn" | null;
  discount_vs_cost_pct: number;
  pullback_pct: number | null;
  below_52w_avg_pct: number | null;
  signal_a: boolean;
  signal_b: boolean;
  mark: string;
  avg_cost_usd: string;
  market_value_usd: string;
  cost_basis_usd: string;
  days_since_buy: number;
  last_buy: string;
  weight_pct: number;
  gate_blockers: string[];
  high_3m?: string | null;
  avg_52w?: string | null;
};

export type DcaBoardResponse = {
  as_of: string;
  stocks: DcaOpportunityItem[];
  crypto: DcaOpportunityItem[];
  meta: {
    history_available: boolean;
    board_min_position_usd?: string;
    alert_min_position_usd?: string;
    cooldown_days?: number;
    max_weight_pct?: number;
  };
};

export type LivingDraw12m = {
  window_days: number;
  window_start: string;
  window_end: string;
  sold_usd: string;
  bought_usd: string;
  draw_usd: string;
  by_ticker: Array<{
    ticker: string;
    sold_usd: string;
    bought_usd: string;
    draw_usd: string;
  }>;
  notes?: string;
};

export type FeeSeriesByPlatform = {
  platform: string;
  amount_usd: string;
};

export type FeeSeriesByType = {
  label: string;
  amount_usd: string;
};

export type FeesSummary = {
  trade_fees_usd: string;
  explicit_fee_events_usd: string;
  total_fees_usd: string;
  deposits_usd: string;
  withdrawals_usd: string;
  fees_by_event_type: Array<{
    label: string;
    amount_usd: string;
    by_platform: FeeSeriesByPlatform[];
  }>;
  fees_by_platform: Array<{
    platform: string;
    amount_usd: string;
    by_type: FeeSeriesByType[];
  }>;
  notes?: string;
};

export type StakingByTicker = {
  ticker: string;
  events: number;
  units: string;
  mark_usd: string;
  broker_usd?: string;
  live_usd?: string;
  mark_source: "broker" | "live" | "mixed" | "unknown" | string;
  platforms: string[];
  first: string;
  last: string;
};

export type StakingSummary = {
  reward_rows: number;
  units_sum?: string;
  mark_usd_total: string;
  broker_mark_usd: string;
  live_mark_usd: string;
  by_ticker: StakingByTicker[];
  notes?: string;
};

export type PortfolioSnapshot = {
  as_of: string;
  ticker_count: number;
  total_cost_basis_usd: string;
  total_cost_basis_czk: string;
  total_market_value_usd: string | null;
  unrealized_usd: string | null;
  unrealized_pct: number | null;
  realized_lifetime_usd: string;
  /** FIFO cost of closed lots that produced realized_lifetime_usd */
  realized_cost_basis_usd?: string;
  realized_proceeds_usd?: string;
  /** gain / cost_sold × 100 when cost known */
  realized_roi_pct?: number | null;
  /** Cost-weighted average hold years of closed lots */
  realized_holding_years?: number | null;
  /** CAGR-style annualized realized ROI % (min ~90d hold) */
  realized_annualized_pct?: number | null;
  tax_free_now_usd: string;
  tax_runway: {
    available_usd: string;
    locked_usd: string;
    buckets: Array<{
      key: string;
      label: string;
      amount_usd: string;
      tickers: Array<{
        ticker: string;
        quantity: string;
        amount_usd: string;
      }>;
    }>;
  };
  prices_as_of: string | null;
  quote_count: number;
  missing_quotes: string[];
  positions: Array<{
    ticker: string;
    quantity: string;
    quantity_tax_free: string;
    quantity_pending: string;
    cost_basis_usd: string;
    cost_basis_czk: string;
    price: string | null;
    market_value: string | null;
    unrealized_usd: string | null;
  }>;
  top_tickers_by_cost: Array<{
    ticker: string;
    cost_usd: string;
    market_value_usd: string | null;
  }>;
  living_draw_12m?: LivingDraw12m;
  fees?: FeesSummary;
  staking?: StakingSummary;
  cashflow_monthly?: Array<{
    month: string;
    bought_usd: string;
    sold_usd: string;
    net_usd: string;
    reinvestment_rate_pct: number | null;
    /** Unbounded cum buys/sells — do not plot (scale killer). */
    cumulative_reinvestment_rate_pct?: number | null;
    /** Chart-safe 0–100%: min(cum buys, cum sells) / cum sells. */
    proceeds_coverage_pct?: number | null;
    cumulative_invested_usd?: string;
    cumulative_proceeds_usd?: string;
    cumulative_net_capital_usd?: string;
  }>;
  health?: {
    score: number;
    grade: string;
    summary: string;
    issues: Array<{ severity: string; title: string; detail: string }>;
    concentration: {
      top_ticker: string | null;
      top_weight_pct: number;
      top3_weight_pct: number;
      hhi: number;
      crypto_weight_pct: number;
      tax_free_basis_pct: number;
      largest_position_line: string;
    };
  };
  price_status?: {
    mode: string;
    quote_count: number;
    open_ticker_count: number;
    missing_quotes: string[];
    prices_as_of: string | null;
    note: string;
    mode_note?: string;
  };
};

export type TickerPlatformSplit = {
  source: string;
  quantity: string;
  cost_basis_usd: string;
  market_value_usd: string;
  lot_count: number;
};

export type TaxTranche = {
  key: string;
  label: string;
  quantity: string;
  market_value_usd: string;
};

export type TickerDigest = {
  ticker: string;
  /** Stock | Crypto when known from open lots */
  asset_class?: string | null;
  quantity_total: string;
  by_platform: TickerPlatformSplit[];
  multi_platform: boolean;
  price_usd: string | null;
  price_as_of: string | null;
  cost_basis_usd: string;
  avg_cost_usd: string;
  market_value_usd: string | null;
  unrealized_usd: string | null;
  unrealized_pct: number | null;
  /** Cost-weighted open holding years (option B) */
  holding_years?: number | null;
  /** CAGR-style annualized open ROI %; null if short hold / unpriced */
  annualized_unrealized_pct?: number | null;
  roi_grade: string;
  roi_grade_label: string;
  portfolio_weight_pct: number;
  unrealized_share_pct: number | null;
  growth_contribution_pp: number | null;
  tax_tranches: TaxTranche[];
  next_unlock_date: string | null;
  next_unlock_quantity: string | null;
  realized_lifetime_usd: string;
  realized_cost_basis_usd?: string;
  realized_proceeds_usd?: string;
  realized_roi_pct?: number | null;
  first_acquired: string | null;
  last_acquired: string | null;
  open_lot_count: number;
  missing_price: boolean;
};

export type PriceHistoryRange =
  | "1d"
  | "7d"
  | "1m"
  | "3m"
  | "6m"
  | "ytd"
  | "1y"
  | "5y";

export type PriceHistoryTrade = {
  date: string;
  side: "buy" | "sell" | string;
  ticker: string;
  quantity: string;
  value_usd?: string | null;
  series_value?: string | null;
};

export type WindowPerformanceItem = {
  ticker: string;
  asset_class?: string | null;
  first_value?: string | null;
  last_value?: string | null;
  change_pct?: number | null;
  change_abs?: string | null;
  currency?: string;
  session_status?: string | null;
};

export type WindowPerformanceResponse = {
  range: string;
  as_of: string;
  items: WindowPerformanceItem[];
};

export type PriceHistory = {
  scope: "ticker" | "asset_class" | "all" | string;
  label: string;
  range: string;
  currency: string;
  series_kind: "price" | "market_value" | string;
  interval?: string;
  as_of: string;
  points: Array<{ date: string; value: string }>;
  meta: {
    tickers?: string[];
    missing_tickers?: string[];
    cost_basis_usd?: string | null;
    avg_cost_usd?: string | null;
    quantity?: string | null;
    first_value?: string | null;
    last_value?: string | null;
    /**
     * change_abs / change_pct = book Δ (chart last − first MV).
     * mark_pnl_abs / mark_pnl_pct = pure mark on qty at window open.
     * net_capital_abs = book − mark (cash/qty residual).
     * Identity: Book = Mark + Net capital.
     * UI toggle (Performance | Book) picks which is primary; math unchanged.
     */
    change_pct?: number | null;
    change_abs?: string | null;
    mv_change_abs?: string | null;
    mv_change_pct?: number | null;
    mark_pnl_abs?: string | null;
    mark_pnl_pct?: number | null;
    net_capital_abs?: string | null;
    open_basis_usd?: string | null;
    window_buys_usd?: string | null;
    window_sells_usd?: string | null;
    change_basis?: string | null;
    day_open?: string | null;
    day_last?: string | null;
    day_change_pct?: number | null;
    day_change_abs?: string | null;
    quantity_basis?: string;
    note?: string;
    point_kind?: string;
    yahoo_symbol?: string | null;
    coverage_threshold?: number | null;
    series_start?: string | null;
    short_history_tickers?: Array<{ ticker: string; first_bar: string }>;
    trades?: PriceHistoryTrade[];
    session_status?: string | null;
    /**
     * Desk book mark (Prices tab × open lots) — same idea as executive snapshot.
     * Not forced onto the 1D path tip; UI shows it next to Chart MV / path last.
     */
    book_market_value_usd?: string | null;
    /** Ticker scope: desk mark for this name. */
    book_price_usd?: string | null;
    /** Path tip − desk book (signed). */
    book_vs_path_abs?: string | null;
    /** Portfolio only: performance split into Stocks + Crypto (ex-flows, additive). */
    window_components?: {
      stocks?: {
        change_usd?: string | null;
        change_pct?: number | null;
        mv_change_usd?: string | null;
        window_buys_usd?: string | null;
        window_sells_usd?: string | null;
        first_usd?: string | null;
        last_usd?: string | null;
      };
      crypto?: {
        change_usd?: string | null;
        change_pct?: number | null;
        mv_change_usd?: string | null;
        window_buys_usd?: string | null;
        window_sells_usd?: string | null;
        first_usd?: string | null;
        last_usd?: string | null;
      };
      sum_change_usd?: string | null;
      sum_change_pct?: number | null;
      sum_mv_change_usd?: string | null;
      first_usd?: string | null;
      last_usd?: string | null;
      method?: string;
      change_basis?: string | null;
    } | null;
  };
};

export type TickerDigestsResponse = {
  as_of: string;
  prices_as_of: string | null;
  portfolio: {
    total_cost_basis_usd: string;
    total_market_value_usd: string | null;
    unrealized_usd: string | null;
    unrealized_pct: number | null;
  };
  tickers: TickerDigest[];
};

export type UploadResult = {
  status: string;
  content_sha256: string;
  parser_key?: string | null;
  institution?: string | null;
  statement_file_id?: string | null;
  rows_parsed: number;
  transactions_written: number;
  events_written: number;
  lots_written: number;
  transfer_pairs_linked: number;
  transactions_deduped: number;
  events_deduped: number;
  message: string;
  errors: string[];
};

export type PriceRefresh = {
  as_of: string;
  quote_count: number;
  total_market_value_usd: string | null;
  quotes: Array<{
    ticker: string;
    price: string;
    currency: string;
    as_of: string;
    source: string;
  }>;
  positions: Array<Record<string, string | null>>;
  errors: string[];
  /** False when soft refresh found no material mark change. */
  quotes_updated?: boolean;
};

export type TaxDisposal = {
  id: string;
  date: string;
  ticker?: string | null;
  quantity?: string | null;
  value_native?: string | null;
  value_czk?: string | null;
  value_usd?: string | null;
  realized_gain_czk?: string | null;
  realized_gain_usd?: string | null;
  holding_period_days?: number | null;
  qualifies_3y_exemption?: boolean | null;
  lot_id?: string | null;
  parent_event_id?: string | null;
  source?: string | null;
  notes?: string | null;
};

export type TaxOpenPosition = {
  ticker: string;
  total_quantity: string;
  quantity_tax_free: string;
  quantity_pending: string;
  cost_basis_native: string;
  cost_basis_czk: string;
  cost_basis_usd: string;
  native_currency: string;
};

export type TaxReport = {
  meta: {
    tax_year: number;
    as_of: string;
    exemption_days: number;
    currency_primary_reporting: string;
    notes: string;
  };
  summary: {
    disposal_count: number;
    exempt_disposal_count: number;
    taxable_disposal_count: number;
    total_realized_gain_czk: string;
    total_realized_gain_usd: string;
    exempt_realized_gain_czk: string;
    taxable_realized_gain_czk: string;
  };
  disposals: TaxDisposal[];
  exempt_disposals: TaxDisposal[];
  taxable_disposals: TaxDisposal[];
  open_positions: TaxOpenPosition[];
};

export type TaxYearsList = {
  years: number[];
  default_year: number;
};

export type TaxYearsSummary = {
  as_of: string;
  years: Array<{
    year: number;
    disposal_count: number;
    exempt_count: number;
    taxable_count: number;
    total_realized_gain_czk: string;
    total_realized_gain_usd: string;
    exempt_realized_gain_czk: string;
    taxable_realized_gain_czk: string;
  }>;
};

export type MvSeriesPoint = {
  date: string;
  total_market_value_usd: string | null;
  total_cost_basis_usd?: string | null;
  unrealized_usd?: string | null;
  tax_free_now_usd?: string | null;
  source?: string;
};

export type MvSeries = {
  date_from: string;
  date_to: string;
  point_count: number;
  series: MvSeriesPoint[];
};

export type DrawMetrics = {
  as_of: string;
  portfolio_mv_usd: string;
  tax_free_now_usd: string;
  safe_draw_pct: string;
  safe_draw_from_pct_usd: string;
  safe_draw_annual_usd: string;
  safe_draw_binding_constraint: string;
  living_draw_12m_usd: string;
  living_sold_usd?: string | null;
  living_bought_usd?: string | null;
  living_over_safe_ratio: string | null;
  status: string;
  formula: string;
  note: string;
};

export type StatementFileRow = {
  id: string;
  original_filename: string;
  uploaded_at: string | null;
  content_sha256: string;
  institution?: string | null;
  row_count?: number | null;
  parser_key?: string | null;
  status: string;
  notes?: string | null;
  has_stored_bytes: boolean;
  retryable: boolean;
};

export type AdminJob = {
  id: string;
  kind: string;
  status: string;
  started_at?: string;
  finished_at?: string | null;
  params?: Record<string, unknown>;
  result?: unknown;
  error?: string | null;
};

export type AdminJobsList = {
  items: AdminJob[];
  kinds: string[];
};

/** CNB USD/CZK history for analysis chart */
export type UsdCzkSeries = {
  pair: string;
  unit: string;
  source: string;
  date_from: string;
  date_to: string;
  point_count: number;
  rate_start: string | null;
  rate_end: string | null;
  change_abs: string | null;
  change_pct: string | null;
  portfolio: {
    portfolio_usd: string;
    portfolio_czk_now: string;
    portfolio_czk_at_period_start_rate: string | null;
    fx_delta_czk: string | null;
    note: string;
  } | null;
  series: Array<{
    date: string;
    rate: string;
    portfolio_czk?: string;
  }>;
  rates_in_sheet: number;
};

export type Paginated<T> = {
  total: number;
  offset: number;
  limit: number;
  items: T[];
};

export type PeriodKey =
  | "this_month"
  | "last_month"
  | "last_30d"
  | "last_6m"
  | "this_year"
  | "last_year"
  | "all_time"
  | "custom"
  | "calendar_month";

export type CategoryRule = {
  id: string;
  priority: number;
  match_field: string;
  match_type: string;
  match_value: string;
  category_id: string;
  set_internal_transfer: boolean;
  institution_scope?: string | null;
  is_active: boolean;
  notes?: string | null;
};

export type CategoryCoverage = {
  days: number;
  expense_usd_total: string;
  expense_usd_categorized: string;
  uncategorized_expense_usd?: string;
  coverage_pct: number;
  target_pct?: number;
  amber_pct?: number;
  status?: "below_target" | "on_target" | "stretch" | string;
  progress_note?: string;
  by_domain: Array<{ name: string; amount_usd: string }>;
  top_uncategorized_merchants: Array<{
    label: string;
    amount_usd: string;
    tx_count?: number;
  }>;
  windows?: {
    "30d"?: { coverage_pct: number; status: string; expense_usd_total: string };
    "180d"?: { coverage_pct: number; status: string; expense_usd_total: string };
  };
  categories_count: number;
  rules_count: number;
};

export type ApplyRulesResult = {
  scanned: number;
  filled: number;
  skipped_override: number;
  skipped_already: number;
  unmatched: number;
  rules_used: number;
};

export type BulkOverrideResult = {
  category_id: string;
  updated: number;
  missing: number;
  transaction_ids: string[];
};

export type ApplyMatchResult = {
  scanned: number;
  matched: number;
  updated: number;
  skipped_override: number;
  skipped_already: number;
  mode: string;
  category_id: string;
  match_field: string;
  match_type: string;
  match_value: string;
};

export type BootstrapRulesResult = {
  ensure: { created: number; updated: number; total_defaults: number };
  rules_created: number;
  rules_total_active: number;
  merchants_mapped: number;
  top_merchants_scanned: number;
  apply: ApplyRulesResult | null;
};
