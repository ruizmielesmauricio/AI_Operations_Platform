/** AC-043 — an opened report shows its expiry date. PROTECTED. */
import { test, expect } from "@playwright/test";
import { login } from "./helpers";

test("AC-043 open report shows expiry", async ({ page }) => {
  await login(page, "OWNER");
  await page.goto("/reports");
  await expect(page.getByRole("heading", { name: "Reports" })).toBeVisible();
  await page.getByRole("link", { name: /weekly/i }).first().click();
  await expect(page).toHaveURL(/\/reports\/[0-9a-f-]{36}/);
  await expect(
    page.getByText(/(expires|available until)[^0-9]*(\d{1,2}[ /]\w+[ /]\d{4}|\d{4}-\d{2}-\d{2})/i).first(),
  ).toBeVisible();
});
