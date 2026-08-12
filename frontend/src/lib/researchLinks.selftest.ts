/**
 * Lightweight regression checks for research URL templates.
 * Run: npx --yes tsx src/lib/researchLinks.selftest.ts  (from frontend/)
 */
import {
  buildResearchLinks,
  coingeckoHref,
  googleFinanceHref,
  tradingViewSymbol,
  yahooSymbol,
} from "./researchLinks";

function assert(cond: unknown, msg: string): asserts cond {
  if (!cond) throw new Error(msg);
}

function byId(links: ReturnType<typeof buildResearchLinks>, id: string) {
  const hit = links.find((l) => l.id === id);
  assert(hit, `missing link id=${id}`);
  return hit;
}

export function runResearchLinksSelftest(): void {
  // --- yahooSymbol ---
  assert(yahooSymbol("btc", "Crypto") === "BTC-USD", "crypto yahoo pair");
  assert(yahooSymbol("AAPL", "Stock") === "AAPL", "stock yahoo bare");
  assert(yahooSymbol("ETH-USD", "Crypto") === "ETH-USD", "already paired");

  // --- Google Finance: stocks never bare /quote/TICKER ---
  for (const t of ["AAPL", "PLTR", "VTI"]) {
    const href = googleFinanceHref(t, "Stock");
    assert(
      href.includes("tbm=fin") && href.includes(encodeURIComponent(t)),
      `stock GF must use fin search: ${t} → ${href}`,
    );
    assert(
      !/\/finance\/quote\/[^?]/.test(href),
      `stock GF must not bare-quote: ${t} → ${href}`,
    );
  }
  assert(
    googleFinanceHref("VTI", "ETF").includes("tbm=fin"),
    "ETF uses fin search",
  );
  assert(
    googleFinanceHref("BTC", "Crypto") ===
      "https://www.google.com/finance/quote/BTC-USD",
    "crypto GF uses BTC-USD quote path",
  );

  // --- CoinGecko ---
  assert(
    coingeckoHref("BTC") === "https://www.coingecko.com/en/coins/bitcoin",
    "BTC deep link",
  );
  assert(
    coingeckoHref("ETH") === "https://www.coingecko.com/en/coins/ethereum",
    "ETH deep link",
  );
  assert(
    coingeckoHref("ZZZUNKNOWN").includes("/en/search?query=ZZZUNKNOWN"),
    "unknown coin search fallback",
  );

  // --- TradingView symbol ---
  assert(tradingViewSymbol("AAPL", "Stock") === "AAPL", "TV stock");
  assert(tradingViewSymbol("BTC", "Crypto") === "BTCUSD", "TV crypto no hyphen");
  assert(tradingViewSymbol("BTC-USD", "Crypto") === "BTCUSD", "TV strip pair");

  // --- buildResearchLinks stock set ---
  const stock = buildResearchLinks("AAPL", "Stock");
  assert(byId(stock, "google-finance").href.includes("tbm=fin"), "stock GF");
  assert(
    byId(stock, "yahoo-finance").href ===
      "https://finance.yahoo.com/quote/AAPL",
    "stock Yahoo",
  );
  assert(
    byId(stock, "tradingview").href ===
      "https://www.tradingview.com/symbols/AAPL/",
    "stock TV",
  );
  assert(
    byId(stock, "x-ticker").href.includes("%24AAPL"),
    "stock cashtag",
  );
  assert(stock.some((l) => l.id === "x-stocks"), "stock x feed");
  assert(!stock.some((l) => l.id === "coingecko"), "no gecko on stock");

  // --- buildResearchLinks crypto set ---
  const crypto = buildResearchLinks("BTC", "Crypto");
  assert(
    byId(crypto, "google-finance").href.endsWith("/quote/BTC-USD"),
    "crypto GF",
  );
  assert(
    byId(crypto, "yahoo-finance").href.endsWith("/quote/BTC-USD"),
    "crypto Yahoo",
  );
  assert(
    byId(crypto, "coingecko").href.endsWith("/coins/bitcoin"),
    "crypto gecko deep",
  );
  assert(
    byId(crypto, "tradingview").href ===
      "https://www.tradingview.com/symbols/BTCUSD/",
    "crypto TV",
  );
  assert(crypto.some((l) => l.id === "x-crypto"), "crypto x feed");
  assert(!crypto.some((l) => l.id === "x-stocks"), "no stocks feed on crypto");

  // --- empty ---
  assert(buildResearchLinks("  ").length === 0, "blank ticker");
  assert(buildResearchLinks("").length === 0, "empty ticker");
}

runResearchLinksSelftest();
console.log("researchLinks.selftest: ok");
