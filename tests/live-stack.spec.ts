import { expect, test } from "@playwright/test";

test("live local stack loads saved Alpaca observations", async ({ page }) => {
  test.skip(process.env.RUN_LIVE !== "1", "Requires running local services and previously ingested Alpaca data.");
  await page.goto("/");
  await expect(page.getByText(/[1-9]\d* of [1-9]\d* contracts/)).toBeVisible({ timeout: 30000 });
  const typeFilter = page.getByLabel("Filter option type");
  await typeFilter.selectOption("call");
  const call = page.getByRole("button", { name: "call", exact: true }).first();
  await expect(call).toBeVisible();
  await call.click();
  await expect(page.getByText("Indicative feed: not executable.", { exact: false }).first()).toBeVisible();
  await expect(page.getByLabel("Hypothetical expiration payoff chart")).toBeVisible();
  await page.getByRole("spinbutton", { name: "Underlying price at expiration" }).fill("250");
  await expect(page.getByText("ESTIMATED P&L")).toBeVisible();
});
