import { expect, test } from "@playwright/test";

test("paper account records hypothetical open and close, and shows backtest blockers", async ({ page }) => {
  let configured = false;
  let opened = false;
  let closed = false;
  let snapshots = 0;
  const openIds: string[] = [];
  const quote = { symbol: "AAPL281215C00100000", ticker: "AAPL", expiration: "2028-12-15", kind: "call", strike: 100, date: "2026-11-17", bid: 4.9, ask: 5, iv: .3, spread: .02, volume: null, open_interest: null, source: "alpaca", feed: "indicative", quote_timestamp: "2026-11-17T12:00:00Z", stale: false, warning: "Indicative feed: not executable." };
  await page.route("**:8000/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    let data: unknown = [];
    if (path === "/health") data = { status: "ok", provider: "alpaca", provider_configured: true };
    else if (path === "/research/status") data = { sec_configured: true, news_configured: true, llm_configured: false };
    else if (path === "/securities/AAPL") data = { ticker: "AAPL", prices: [{ date: "2026-11-16", close: 100 }], realized_volatility: .2, last_ingestion: null };
    else if (path === "/securities/AAPL/options") data = [quote];
    else if (path === "/backtests/readiness") data = { status: "incomplete", saved_quote_count: 10, blockers: ["Verified historical data is missing."] };
    else if (path === "/paper/account" && request.method() === "POST") { configured = true; data = {}; }
    else if (path === "/paper/positions" && request.method() === "POST") {
      opened = true;
      openIds.push(request.postDataJSON().request_id);
      if (openIds.length === 1) {
        await route.fulfill({ status: 503, json: { detail: "Temporary response failure" }, headers: { "Access-Control-Allow-Origin": "*" } });
        return;
      }
      data = {};
    }
    else if (path === "/paper/positions/1/close" && request.method() === "POST") { closed = true; data = {}; }
    else if (path === "/paper/valuations" && request.method() === "POST") { snapshots++; data = {}; }
    else if (path === "/paper/valuations") data = snapshots ? [{ id: 1, observed_at: "2026-11-17T12:00:00Z", cash: 9000, equity: null }] : [];
    else if (path === "/paper") data = !configured ? { configured: false, positions: [] } : { initial_cash: 10000, cash: 9000, equity: null, realized_profit: 0, total_return: null, incomplete_marks: 1, closed_positions: 0, win_rate: null, average_closed_return: null, sampled_max_drawdown: null, sampled_valuation_count: snapshots, benchmark: { status: "unavailable", reason: "No benchmark" }, positions: opened ? [{ id: 1, ticker: "AAPL", symbol: quote.symbol, kind: "call", strike: 100, expiration: quote.expiration, remaining_quantity: closed ? 0 : 1, initial_quantity: 1, entry_price: 5, entry_fee: 1, realized_profit: 0, unrealized_profit: null, mark_per_share: null, warnings: ["Quote is stale."], fills: [] }] : [] };
    await route.fulfill({ json: data, headers: { "Access-Control-Allow-Origin": "*" } });
  });
  await page.goto("/");
  await expect(page.getByText("Verified historical data is missing.")).toBeVisible();
  await page.getByLabel("Starting paper cash ($)").fill("10000");
  await page.getByRole("button", { name: "Create paper account" }).click();
  await expect(page.getByText("Paper account created.")).toBeVisible();
  await page.getByRole("button", { name: "call", exact: true }).first().click();
  await page.getByLabel("Paper contracts", { exact: true }).fill("1");
  await page.getByLabel("Paper entry price per share").fill("5");
  await page.getByLabel("Paper entry fees").fill("1");
  await page.getByRole("button", { name: "Record paper position" }).click();
  await expect(page.getByText("Temporary response failure")).toBeVisible();
  await page.getByRole("button", { name: "Record paper position" }).click();
  await expect(page.getByText("Hypothetical position recorded.")).toBeVisible();
  expect(openIds).toHaveLength(2);
  expect(openIds[0]).toBe(openIds[1]);
  await expect(page.getByText("Quote is stale.")).toBeVisible();
  await page.getByRole("button", { name: "Save valuation snapshot" }).click();
  await expect(page.getByText("Valuation snapshot saved.")).toBeVisible();
  await page.getByRole("button", { name: "Record paper close" }).click();
  await page.getByLabel("Paper close contracts").fill("1");
  await page.getByLabel("Paper close price per share").fill("6");
  await page.getByLabel("Paper close fees").fill("1");
  await page.getByRole("button", { name: "Save paper close" }).click();
  await expect(page.getByText("Hypothetical close recorded.")).toBeVisible();
});
