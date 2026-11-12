/** AC-019 — UI terminology adapts to the business type. PROTECTED. */
import { test, expect } from "@playwright/test";
import { BIKE_WORDS, login } from "./helpers";

test("AC-019 terminology adapts to template", async ({ page }) => {
  await login(page, "OWNER");
  for (const path of ["/dashboard", "/uploads", "/reports", "/chat", "/products", "/transactions"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const text = await page.locator("body").innerText();
    const hit = text.match(BIKE_WORDS);
    expect(hit, `coffee shop sees "${hit?.[0]}" on ${path}`).toBeNull();
  }
});
