import { expect, test } from "@playwright/test";

test("live saved opportunities follow ticker selection", async ({ page }) => {
  test.skip(process.env.RUN_LIVE !== "1", "Requires saved Alpaca observations.");
  await page.goto("/");
  await page.getByLabel("Include stale quotes").check();
  const table = page.locator("#explorer + .panel");
  for (const ticker of ["MSFT", "TSLA"]) {
    await page.getByLabel("Opportunity ticker").selectOption(ticker);
    await expect(table.getByText(`${ticker} screen results`)).toBeVisible();
    await expect.poll(() => table.locator("tbody tr").count(), { timeout: 30000 }).toBeGreaterThan(0);
    for (const row of await table.locator("tbody tr").all()) await expect(row.locator("td").first()).toHaveText(ticker);
  }
});
