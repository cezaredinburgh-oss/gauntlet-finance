/**
 * External research URLs for a ticker / asset class.
 * Client-only; no PII. Open with target=_blank + rel=noopener noreferrer.
 */

export type ResearchLink = {
  id: string;
  label: string;
  href: string;
  description?: string;
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

  const links: ResearchLink[] = [
    {
      id: "google-finance",
      label: "Google Finance",
      href: `https://www.google.com/finance/quote/${yq}`,
      description: "Quotes and news",
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
      label: "CoinGecko search",
      href: `https://www.coingecko.com/en/search?query=${q}`,
      description: "Market data",
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
      href: `https://www.tradingview.com/symbols/${yq}/`,
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
