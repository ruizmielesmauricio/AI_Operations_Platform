/** AC-071, AC-072, AC-076, AC-077 — dashboard. PROTECTED. */
import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { login } from "./helpers";

test("AC-071 charts render client-side from api", async ({ page }) => {
  await login(page, "OWNER");
  const apiCall = page.waitForResponse((r) => /\/analytics\/financial-performance/.test(r.url()) && r.ok());
  await page.goto("/dashboard");
  const resp = await apiCall;
  expect(resp.headers()["content-type"]).toContain("application/json");
  const charts = page.locator("[_echarts_instance_]");
  await expect(charts.first()).toBeVisible();
  expect(await charts.first().locator("canvas, svg").count()).toBeGreaterThan(0);
  const serverImages = await page.locator('img[src*="chart"], img[src*="/analytics/"]').count();
  expect(serverImages).toBe(0);
});

test("AC-072 metric definitions on demand", async ({ page }) => {
  await login(page, "OWNER");
  await page.goto("/dashboard");
  const triggers = page.getByRole("button", { name: /definition|what (is|does)|about this metric/i });
  expect(await triggers.count()).toBeGreaterThanOrEqual(3);
  await triggers.first().click();
  const shown = page.locator('[role="tooltip"], [role="dialog"], [role="note"]').filter({ hasText: /\w{4,}.{20,}/ });
  await expect(shown.first()).toBeVisible();
});

test("AC-076 accessible", async ({ page }) => {
  await login(page, "OWNER");
  await page.goto("/dashboard");
  await page.waitForLoadState("networkidle");
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  const charts = page.locator("[_echarts_instance_]");
  for (let i = 0; i < (await charts.count()); i++) {
    const label = (await charts.nth(i).getAttribute("aria-label")) || (await charts.nth(i).locator("[aria-label]").first().getAttribute("aria-label").catch(() => null));
    expect(label, `chart ${i} has no text alternative`).toBeTruthy();
  }
  await page.keyboard.press("Tab");
  const focused = await page.evaluate(() => document.activeElement?.tagName);
  expect(focused).not.toBe("BODY");
});

test("AC-077 mobile readable", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await ctx.newPage();
  await login(page, "OWNER");
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "horizontal scroll on a 375px screen").toBeLessThanOrEqual(0);
  await ctx.close();
});
