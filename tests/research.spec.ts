import { expect, test } from "@playwright/test";

test("research displays sources, partial errors, and cited AI interpretations", async ({ page }) => {
  let generated = false;
  const source = { id: 101, provider: "sec", kind: "10-K", title: "Example filing", url: "https://www.sec.gov/example", published_on: "2026-01-01", retrieved_at: "2026-11-17T12:00:00Z", coverage: "truncated_excerpt", content: "The company reported a material change in operations." };
  const statement = { text: "Operations could improve.", citations: [{ source_id: 101, quote: "The company reported a material change in operations." }] };
  const report = { id: 1, created_at: "2026-11-17T12:00:00Z", model: "test", report: { market_view: [], catalysts: [], bullish: { outcome: statement, evidence_against: [] }, neutral: null, bearish: null, reasons_correctly_priced: [], open_questions: ["What further evidence is needed?"] } };
  await page.route("**/research/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown;
    if (path.endsWith("/status")) data = { sec_configured: true, news_configured: true, llm_configured: true };
    else if (path.endsWith("/sources/refresh")) data = { new_sources: 1, errors: { alpaca_news: "News unavailable" } };
    else if (path.endsWith("/sources")) data = [source];
    else if (path.endsWith("/reports") && route.request().method() === "POST") { generated = true; data = report; }
    else data = generated ? [report] : [];
    await route.fulfill({ json: data, headers: { "Access-Control-Allow-Origin": "*" } });
  });
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Example filing" })).toBeVisible();
  await page.getByRole("button", { name: "Retrieve sources" }).click();
  await expect(page.getByRole("status")).toContainText("News unavailable");
  await page.getByRole("checkbox", { name: /10-K/ }).check();
  await page.getByRole("button", { name: "Generate research report" }).click();
  await expect(page.getByText("Operations could improve.")).toBeVisible();
  await page.getByText("Source 101").click();
  await expect(page.locator("blockquote").getByText("The company reported a material change in operations.", { exact: true })).toBeVisible();
  await expect(page.getByText("AI-generated interpretations and hypotheses.", { exact: false })).toBeVisible();
});
test("select all and deselect all include every source while preserving report limit", async ({ page }) => {
  const sources = Array.from({ length: 10 }, (_, index) => ({
    id: index + 1, provider: "sec", kind: "10-K", title: `Filing ${index + 1}`,
    url: "https://www.sec.gov/example", published_on: "2026-01-01",
    retrieved_at: "2026-11-17T12:00:00Z", coverage: "full_text", content: "Example filing text.",
  }));
  await page.route("**/research/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const data = path.endsWith("/status") ? { sec_configured: true, news_configured: true, llm_configured: true } : path.endsWith("/sources") ? sources : [];
    await route.fulfill({ json: data, headers: { "Access-Control-Allow-Origin": "*" } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Select all", exact: true }).click();
  await expect(page.getByText("10 sources selected")).toBeVisible();
  await expect(page.locator(".source-item input:checked")).toHaveCount(10);
  await expect(page.getByRole("button", { name: "Generate research report" })).toBeDisabled();
  await expect(page.getByText("Select up to 8 sources to generate an AI report.")).toBeVisible();
  await page.getByRole("button", { name: "Deselect all", exact: true }).click();
  await expect(page.locator(".source-item input:checked")).toHaveCount(0);
});
