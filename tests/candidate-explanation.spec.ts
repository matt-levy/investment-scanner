import { expect, test } from "@playwright/test";

test("candidate explanation calculates expiration outcomes with explicitly entered fees", async ({ page }) => {
  const quote = { symbol:"AAPL-TEST", ticker:"AAPL", expiration:"2028-01-21", kind:"call", strike:100,
    date:"2026-11-17", bid:2, ask:3, iv:.3, iv_minus_rv:-.1, spread:.4, volume:15,
    open_interest:40, source:"alpaca", feed:"indicative", stale:false };
  await page.route("**:8000/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = [];
    if (path === "/health") data = { status:"ok", provider:"alpaca", provider_configured:true };
    else if (path === "/scan") data = [quote];
    else if (path === "/research/status") data = { sec_configured:false, news_configured:false, llm_configured:false };
    else if (path === "/securities/AAPL") data = { ticker:"AAPL", prices:[{date:"2026-11-16",close:100}], realized_volatility:.4, last_ingestion:null };
    await route.fulfill({ json:data, headers:{ "Access-Control-Allow-Origin":"*" } });
  });
  await page.goto("/");
  await page.getByRole("button", { name:"CALL $100.00" }).click();
  const panel = page.getByRole("region", { name:"Selected candidate explanation" });
  await expect(panel).toContainText("Enter fees to calculate");
  await panel.getByLabel("Total assumed fees per contract").fill("2");
  await expect(panel).toContainText("$103.02");
  await expect(panel).toContainText("$302.00");
  await expect(panel.getByRole("row", { name:/10% higher/ })).toContainText("$698.00");
  await expect(panel).toContainText("Indicative prices are estimates");
  await expect(panel).toContainText("No saved sources");
});
