import { expect, test } from "@playwright/test";

test("watchlist saves user assumptions and reloads prior versions", async ({ page }) => {
  const quote = { symbol: "AAPL281215C00100000", ticker: "AAPL", expiration: "2028-12-15", kind: "call", strike: 100, date: "2026-11-17", bid: 4.9, ask: 5, iv: .3, spread: .02, volume: null, open_interest: null, source: "alpaca", feed: "indicative", quote_timestamp: "2026-11-17T12:00:00Z", stale: true, warning: "Indicative feed: not executable." };
  const item = { id: 1, ticker: "AAPL", symbol: quote.symbol, kind: "call", strike: 100, expiration: quote.expiration, current_quote: quote };
  let added = false;
  const assessments: unknown[] = [];
  const source = { id: 7, title: "Example source", url: "https://www.sec.gov/example", kind: "10-K", published_on: "2026-01-01", provider: "sec", coverage: "full_text", retrieved_at: "2026-11-17T12:00:00Z", content: "Example source." };
  const snapshots: unknown[] = [];
  let lastSaved: Record<string, unknown> | null = null;
  await page.route("**:8000/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    let data: unknown = [];
    if (path === "/health") data = { status: "ok", provider: "alpaca", provider_configured: true };
    else if (path === "/research/status") data = { sec_configured: true, news_configured: true, llm_configured: false };
    else if (path === "/research/AAPL/sources") data = [source];
    else if (path.endsWith("/assessments") && request.method() === "POST") {
      assessments.unshift({ id: 1, created_at: "2026-11-17T12:00:00Z", inputs: request.postDataJSON() });
      data = assessments[0];
    } else if (path.endsWith("/assessments")) data = assessments;
    else if (path === "/securities/AAPL") data = { ticker: "AAPL", prices: [{ date: "2026-11-16", close: 100 }], realized_volatility: .2, last_ingestion: null };
    else if (path === "/securities/AAPL/options") data = [quote];
    else if (path === "/watchlist" && request.method() === "POST") { added = true; data = item; }
    else if (path === "/watchlist") data = added ? [item] : [];
    else if (path.endsWith("/quotes")) data = [quote];
    else if (path.endsWith("/scenarios") && request.method() === "POST") {
      const assumptions = request.postDataJSON();
      lastSaved = assumptions;
      snapshots.unshift({ id: snapshots.length + 1, created_at: "2026-11-17T12:00:00Z", assumptions, results: { expected_value: -10 }, quote_snapshot: quote });
      data = snapshots[0];
    } else if (path.endsWith("/scenarios")) data = snapshots;
    await route.fulfill({ json: data, headers: { "Access-Control-Allow-Origin": "*" } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "call", exact: true }).first().click();
  await page.getByRole("button", { name: "Add to watchlist" }).click();
  await page.getByRole("button", { name: "AAPL call $100.00" }).click();
  await expect(page.getByRole("button", { name: "Save assumptions" })).toBeDisabled();
  await page.getByLabel("Option purchase price per share").fill("5");
  await page.getByLabel("Transaction costs per contract").fill("10");
  for (const [name, price, probability] of [["Bullish", "120", "25"], ["Neutral", "100", "50"], ["Bearish", "80", "25"]]) {
    await page.getByLabel(`${name} price`).fill(price);
    await page.getByLabel(`${name} probability`).fill(probability);
  }
  await expect(page.getByText("Break-even bullish probability", { exact: false })).toContainText("25.5%");
  await page.getByRole("button", { name: "Save assumptions" }).click();
  await expect(page.getByText("Assumptions saved.")).toBeVisible();
  await page.getByText("Saved assumptions (1)").click();
  await page.getByLabel("Option purchase price per share").fill("6");
  await page.getByRole("button", { name: "Load", exact: true }).click();
  await expect(page.getByLabel("Option purchase price per share")).toHaveValue("5");
  await page.getByLabel("Valuation timing").selectOption("before");
  await page.getByLabel("Sale date").fill("2027-12-16");
  await page.getByLabel("Annual risk-free rate").fill("5");
  await page.getByLabel("Annual dividend yield").fill("0");
  for (const name of ["Bullish", "Neutral", "Bearish"]) await page.getByLabel(`${name} volatility`).fill("20");
  await expect(page.getByText("$10.45", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Save assumptions" }).click();
  await expect.poll(() => lastSaved?.valuation_date).toBe("2027-12-16");
  await expect.poll(() => (lastSaved?.scenarios as { volatility: number }[] | undefined)?.[0].volatility).toBe(.2);
  await page.getByText("Research assessment", { exact: false }).first().click();
  await page.getByLabel("Catalyst relevance").selectOption("high");
  await page.getByLabel("Evidence quality").selectOption("mixed");
  await page.getByRole("checkbox", { name: /Example source/ }).check();
  await page.getByRole("button", { name: "Save assessment" }).click();
  await expect(page.getByText("Assessment saved.")).toBeVisible();
});
