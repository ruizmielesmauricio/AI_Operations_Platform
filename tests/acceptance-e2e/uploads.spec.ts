/** AC-032 — messy CSV upload shows an import summary. PROTECTED. Needs a dev R2 bucket. */
import { test, expect } from "@playwright/test";
import * as path from "path";
import { login } from "./helpers";

test("AC-032 messy csv imports with summary", async ({ page }) => {
  await login(page, "OWNER");
  await page.goto("/uploads");
  await expect(page.getByRole("heading", { name: "Upload data" })).toBeVisible();
  await page.locator('input[type="file"]').first().setInputFiles(path.join(__dirname, "fixtures", "messy_sales.csv"));
  await page.locator('input[type="file"]').first().locator("xpath=ancestor::form").getByRole("button").last().click();

  const proceed = page.getByRole("button", { name: /confirm|looks right|import|continue/i }).first();
  for (let i = 0; i < 3; i++) {
    if (await page.getByText(/imported/i).first().isVisible().catch(() => false)) break;
    if (await proceed.isVisible().catch(() => false)) await proceed.click();
    await page.waitForTimeout(1500);
  }
  await expect(page.getByText(/\b3\b[^.]*imported|imported[^.]*\b3\b/i).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/1 rows? skipped|skipped[^.]*\b1\b/i).first()).toBeVisible();
  await expect(page.getByText(/Traceback|Exception|stack/i)).toHaveCount(0);
});
