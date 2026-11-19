import { expect, test } from "@playwright/test";

test("filter and paginate the full chain and inspect hypothetical charts", async ({ page }) => {
  const rows = Array.from({ length: 130 }, (_, i) => ({
    symbol: `TEST${i}`, ticker: "AAPL", expiration: i < 65 ? "2028-01-21" : "2028-06-16",
    kind: i % 2 ? "put" : "call", strike: 100 + i, date: "2026-11-17", bid: 2,
    ask: 3, iv: 0.3, spread: 0.4, volume: null, open_interest: null,
    source: "alpaca", feed: "indicative", quote_timestamp: "2026-11-17T12:00:00Z",
    stale: true, warning: "Indicative feed: not executable. Quote is stale.",
  }));
  await page.route("**:8000/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const data = path === "/watchlist" ? [] : path === "/research/status" ? { sec_configured: false, news_configured: false, llm_configured: false } : path.includes("/research/") ? [] : path === "/health" ? { status: "ok", provider: "alpaca", provider_configured: true } :
      path === "/scan" ? [] : path.endsWith("/options") ? rows :
      { ticker: "AAPL", prices: [{ date: "2026-11-16", close: 150 }], realized_volatility: 0.2, last_ingestion: null };
    await route.fulfill({ json: data, headers: { "Access-Control-Allow-Origin": "*" } });
  });
  await page.goto("/");
  await expect(page.getByText("130 of 130 contracts")).toBeVisible();
  await expect(page.getByText("Page 1 of 6")).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText("Page 2 of 6")).toBeVisible();
  await page.getByLabel("Filter expiration").selectOption("2028-06-16");
  await page.getByLabel("Filter option type").selectOption("call");
  await page.getByLabel("Minimum strike").fill("200");
  await expect(page.getByText("Page 1 of 1")).toBeVisible();
  await expect(page.getByLabel("Implied volatility by strike", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "call", exact: true }).first().click();
  await expect(page.getByLabel("Hypothetical expiration payoff chart")).toBeVisible();
  await expect(page.getByText("Indicative feed: not executable. Quote is stale.")).toBeVisible();
  await page.getByRole("spinbutton", { name: "Underlying price at expiration" }).fill("250");
  await expect(page.getByText("$4700.00")).toBeVisible();
});
