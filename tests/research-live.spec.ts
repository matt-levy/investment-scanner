import { expect, test } from "@playwright/test";

test("live research displays retrieved source links", async ({ page }) => {
  test.skip(process.env.RUN_LIVE !== "1", "Requires configured Alpaca credentials and saved AAPL news.");
  await page.goto("/");
  await expect(page.locator("#research .source-item").first()).toBeVisible({ timeout: 30000 });
  await expect(page.locator("#research .source-item a").first()).toHaveAttribute("href", /^https:\/\//);
});
