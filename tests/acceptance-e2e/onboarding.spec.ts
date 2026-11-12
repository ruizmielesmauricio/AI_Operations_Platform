/** AC-058 — at most six questions before the first upload screen. PROTECTED. */
import { test, expect } from "@playwright/test";
import { login } from "./helpers";

test("AC-058 at most six questions before upload", async ({ page }) => {
  await login(page, "ONBOARD");
  await page.goto("/onboarding");
  const form = page.locator("form").filter({ has: page.getByLabel("Business type") });
  await expect(form).toBeVisible();
  const questions = await form.locator("input:not([type=hidden]):not([type=checkbox]), select, textarea").count();
  expect(questions).toBeLessThanOrEqual(6);

  const type = page.getByLabel("Business type");
  const options = await type.locator("option").allTextContents();
  expect(options.some((o) => /coffee/i.test(o)), `business types offered: ${options}`).toBeTruthy();
  await page.getByLabel("Business name").fill(`Onboard ${Date.now()}`);
  await type.selectOption({ label: options.find((o) => /coffee/i.test(o))! });
  await page.getByRole("button", { name: "Create business" }).click();

  await page.goto("/uploads");
  await expect(page.getByRole("heading", { name: "Upload data" })).toBeVisible();
});
