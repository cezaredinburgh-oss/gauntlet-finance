/**
 * External research URLs for a ticker / asset class.
 * Client-only; no PII. Open with target=_blank + rel=noopener noreferrer.
 *
 * Google Finance equities require SYMBOL:EXCHANGE; bare /quote/TICKER 404s.
 * Stocks/ETFs therefore use Google Finance search (tbm=fin), which resolves
 * the listing. Crypto quotes use Yahoo-style TICKER-USD on Google/Yahoo.
 */

export type ResearchLink = {
  id: string;
  label: string;
  href: string;
  description?: string;
};

/** CoinGecko coin ids for liquid majors (ticker → path slug). */
const COINGECKO_IDS: Record<string, string> = {
  BTC: "bitcoin",
  ETH: "ethereum",
  SOL: "solana",
  ADA: "cardano",
  XRP: "ripple",
  DOGE: "dogecoin",
  DOT: "polkadot",
  AVAX: "avalanche-2",
  MATIC: "matic-network",
  POL: "polygon-ecosystem-token",
  LINK: "chainlink",
  UNI: "uniswap",
  ATOM: "cosmos",
  LTC: "litecoin",
  BNB: "binancecoin",
  BCH: "bitcoin-cash",
  NEAR: "near",
  APT: "aptos",
  ARB: "arbitrum",
  OP: "optimism",
  SUI: "sui",
  TON: "the-open-network",
  TRX: "tron",
  XLM: "stellar",
  ALGO: "algorand",
  FIL: "filecoin",
  ICP: "internet-computer",
  HBAR: "hedera-hashgraph",
  SHIB: "shiba-inu",
  PEPE: "pepe",
  AAVE: "aave",
  MKR: "maker",
  CRV: "curve-dao-token",
  RENDER: "render-token",
  INJ: "injective-protocol",
  SEI: "sei-network",
  TIA: "celestia",
  WIF: "dogwifcoin",
  BONK: "bonk",
};

function isCrypto(assetClass?: string | null): boolean {
  return (assetClass || "").toLowerCase() === "crypto";
}

/** Yahoo quote symbol: crypto uses TICKER-USD. */
export function yahooSymbol(ticker: string, assetClass?: string | null): string {
  const t = ticker.trim().toUpperCase();
  if (!t) return t;
  if (isCrypto(assetClass) && !t.includes("-")) return `${t}-USD`;
  return t;
}

/** Google Finance: equities need exchange resolution; crypto uses Yahoo pair. */
export function googleFinanceHref(
  ticker: string,
  assetClass?: string | null,
): string {
  const t = ticker.trim().toUpperCase();
  if (!t) return "https://www.google.com/finance/";
  if (isCrypto(assetClass)) {
    const ysym = yahooSymbol(t, assetClass);
    return `https://www.google.com/finance/quote/${encodeURIComponent(ysym)}`;
  }
  // tbm=fin resolves SYMBOL:EXCHANGE (bare /quote/TICKER is 404 on GF beta)
  return `https://www.google.com/search?q=${encodeURIComponent(t)}&tbm=fin`;
}

export function coingeckoHref(ticker: string): string {
  const t = ticker.trim().toUpperCase();
  const id = COINGECKO_IDS[t];
  if (id) return `https://www.coingecko.com/en/coins/${id}`;
  return `https://www.coingecko.com/en/search?query=${encodeURIComponent(t)}`;
}

/** TradingView path symbol (no colon): equities bare; crypto TICKERUSD. */
export function tradingViewSymbol(
  ticker: string,
  assetClass?: string | null,
): string {
  const t = ticker.trim().toUpperCase();
  if (!t) return t;
  if (isCrypto(assetClass)) {
    // BTC-USD / BTC → BTCUSD (BTC-USD path 404s on TradingView)
    const base = t.includes("-") ? t.split("-")[0]! : t;
    return `${base}USD`;
  }
  return t;
}

export function buildResearchLinks(
  ticker: string,
  assetClass?: string | null,
): ResearchLink[] {
  const t = ticker.trim().toUpperCase();
  if (!t) return [];
  const ysym = yahooSymbol(t, assetClass);
  const crypto = isCrypto(assetClass);
  const q = encodeURIComponent(t);
  const yq = encodeURIComponent(ysym);
  const tv = encodeURIComponent(tradingViewSymbol(t, assetClass));

  const links: ResearchLink[] = [
    {
      id: "google-finance",
      label: "Google Finance",
      href: googleFinanceHref(t, assetClass),
      description: crypto ? "Quotes and news" : "Quotes and news (resolves exchange)",
    },
    {
      id: "yahoo-finance",
      label: "Yahoo Finance",
      href: `https://finance.yahoo.com/quote/${yq}`,
      description: "Charts and fundamentals",
    },
    {
      id: "x-ticker",
      label: `$${t} on X`,
      href: `https://x.com/search?q=%24${q}&src=typed_query&f=live`,
      description: "Live cashtag discussion",
    },
  ];

  if (crypto) {
    links.push({
      id: "x-crypto",
      label: "Crypto on X",
      href: "https://x.com/search?q=crypto&src=typed_query&f=live",
      description: "Crypto feed",
    });
    links.push({
      id: "coingecko",
      label: COINGECKO_IDS[t] ? "CoinGecko" : "CoinGecko search",
      href: coingeckoHref(t),
      description: "Market data",
    });
    links.push({
      id: "tradingview",
      label: "TradingView",
      href: `https://www.tradingview.com/symbols/${tv}/`,
      description: "Technical chart",
    });
  } else {
    links.push({
      id: "x-stocks",
      label: "Stocks on X",
      href: "https://x.com/search?q=stocks%20OR%20equities&src=typed_query&f=live",
      description: "Equity discussion",
    });
    links.push({
      id: "tradingview",
      label: "TradingView",
      href: `https://www.tradingview.com/symbols/${tv}/`,
      description: "Technical chart",
    });
  }

  return links;
}

/** Group-level links when viewing All stocks / All crypto / Portfolio. */
export function buildGroupResearchLinks(
  kind: "all" | "stock" | "crypto",
): ResearchLink[] {
  if (kind === "crypto") {
    return [
      {
        id: "x-crypto",
        label: "Crypto on X",
        href: "https://x.com/search?q=crypto&src=typed_query&f=live",
      },
      {
        id: "coingecko",
        label: "CoinGecko",
        href: "https://www.coingecko.com/",
      },
      {
        id: "yahoo-crypto",
        label: "Yahoo Crypto",
        href: "https://finance.yahoo.com/crypto/",
      },
    ];
  }
  if (kind === "stock") {
    return [
      {
        id: "x-stocks",
        label: "Stocks on X",
        href: "https://x.com/search?q=stocks%20OR%20equities&src=typed_query&f=live",
      },
      {
        id: "google-finance",
        label: "Google Finance",
        href: "https://www.google.com/finance/",
      },
      {
        id: "yahoo-markets",
        label: "Yahoo Markets",
        href: "https://finance.yahoo.com/",
      },
    ];
  }
  return [
    {
      id: "google-finance",
      label: "Google Finance",
      href: "https://www.google.com/finance/",
    },
    {
      id: "yahoo-finance",
      label: "Yahoo Finance",
      href: "https://finance.yahoo.com/",
    },
    {
      id: "x-markets",
      label: "Markets on X",
      href: "https://x.com/search?q=markets%20OR%20stocks%20OR%20crypto&src=typed_query&f=live",
    },
  ];
}
