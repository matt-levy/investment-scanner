import { expect, test } from "@playwright/test";

test("opportunities follow the selected ticker and can show all tickers", async ({ page }) => {
  const quotes = ["AAPL", "MSFT", "TSLA"].map((ticker, index) => ({
    symbol: `${ticker}-TEST`, ticker, expiration: "2028-01-21", kind: "call", strike: 100 + index,
    date: "2026-11-17", bid: 2, ask: 3, iv: .3, iv_minus_rv: -.1, spread: .4,
    volume: null, open_interest: null, source: "alpaca", feed: "indicative", stale: false,
  }));
  await page.route("**:8000/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = [];
    if (path === "/health") data = { status: "ok", provider: "alpaca", provider_configured: true };
    else if (path === "/research/status") data = { sec_configured: false, news_configured: false, llm_configured: false };
    else if (path === "/scan") data = quotes;
    else if (path.startsWith("/securities/") && !path.endsWith("/options")) data = { ticker: path.split("/")[2], prices: [], realized_volatility: .2, last_ingestion: null };
    await route.fulfill({ json: data, headers: { "Access-Control-Allow-Origin": "*" } });
  });
  await page.goto("/");
  const table = page.locator("#explorer + .panel");
  await expect(table.getByText("AAPL screen results")).toBeVisible();
  await expect(table.locator("tbody tr")).toHaveCount(1);
  await expect(table.locator("tbody tr").first()).toContainText("AAPL");
  await page.getByLabel("Opportunity ticker").selectOption("TSLA");
  await expect(table.getByText("TSLA screen results")).toBeVisible();
  await expect(table.locator("tbody tr")).toHaveCount(1);
  await expect(table.locator("tbody tr").first()).toContainText("TSLA");
  await page.getByLabel("Select ticker", { exact: true }).selectOption("MSFT");
  await expect(table.getByText("MSFT screen results")).toBeVisible();
  await expect(table.locator("tbody tr").first()).toContainText("MSFT");
  await page.getByLabel("Show all tickers").check();
  await expect(table.locator("tbody tr")).toHaveCount(3);
  await page.getByLabel("Filter by ticker").fill("AAPL");
  await expect(table.locator("tbody tr")).toHaveCount(1);
  await expect(table.locator("tbody tr").first()).toContainText("AAPL");
});
