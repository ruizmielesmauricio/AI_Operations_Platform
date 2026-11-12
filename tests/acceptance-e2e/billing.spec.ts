/** AC-050 — an unpaid owner reaches Stripe Checkout (test mode). PROTECTED. Needs STRIPE_SECRET_KEY=sk_test_. */
import { test, expect } from "@playwright/test";
import { login } from "./helpers";

test("AC-050 unpaid owner reaches checkout", async ({ page }) => {
  await login(page, "RESET");
  await page.goto("/uploads");
  await page.getByRole("button", { name: /subscribe/i }).first().click();
  await expect(page).toHaveURL(/checkout\.stripe\.com/, { timeout: 30_000 });
  await expect(page.getByText(/80[.,]00/).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/test mode|sandbox/i).first()).toBeVisible();
});
