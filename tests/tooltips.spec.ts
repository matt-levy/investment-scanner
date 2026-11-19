import { test, expect } from "@playwright/test";

test("financial definitions work with hover, focus, click, and escape", async ({ page }) => {
  await page.goto("/");
  const securities = page.getByRole("button", { name: "About SECURITIES" });
  await securities.hover();
  const tooltip = page.getByRole("tooltip");
  await expect(tooltip).toContainText("financial asset");
  await expect(tooltip).toBeInViewport();
  await expect(tooltip).toHaveCSS("position", "fixed");
  await expect(tooltip).toHaveCSS("background-color", "rgb(255, 255, 255)");
  await expect(securities).toHaveCSS("cursor", "pointer");
  const triggerBox = await securities.boundingBox();
  const tooltipBox = await tooltip.boundingBox();
  expect(tooltipBox!.y + tooltipBox!.height).toBeLessThan(triggerBox!.y);
  await page.mouse.move(0, 0);
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await securities.focus();
  await expect(page.getByRole("tooltip")).toContainText("financial asset");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await securities.click();
  await expect(page.getByRole("tooltip")).toContainText("financial asset");
  await page.locator("h1").click();
  await expect(page.getByRole("tooltip")).toHaveCount(0);
});

test("table tooltip is not clipped by the scrolling container", async ({ page }) => {
  await page.goto("/");
  const iv = page.getByRole("button", { name: "About IV", exact: true }).first();
  await iv.hover();
  const tooltip = page.getByRole("tooltip");
  await expect(tooltip).toContainText("Implied volatility");
  const box = await tooltip.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.y + box!.height).toBeLessThanOrEqual(720);
  expect(box!.x + box!.width).toBeLessThanOrEqual(1280);
});

test.describe("touch", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  test("tap reveals a definition and tap outside dismisses it", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "About SECURITIES" }).tap();
    const tooltip = page.getByRole("tooltip");
    await expect(tooltip).toContainText("financial asset");
    await expect(tooltip).toBeInViewport();
    await expect(tooltip).toHaveCSS("position", "fixed");
    const box = await tooltip.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x + box!.width).toBeLessThanOrEqual(390);
    await page.locator("h1").tap();
    await expect(tooltip).toHaveCount(0);
  });
});
