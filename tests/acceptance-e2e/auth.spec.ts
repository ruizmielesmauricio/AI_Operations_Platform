/** AC-056, AC-057 — auth in the browser. PROTECTED. */
import { test, expect, type APIRequestContext } from "@playwright/test";
import { accessToken, creds, env, login } from "./helpers";

test("AC-056 login, redirect, logout", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login/);
  await login(page, "OWNER");
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login/);
});

async function currentResetPassword(request: APIRequestContext): Promise<{ current: string; next: string }> {
  const base = creds("RESET").password;
  const rotated = `${base}-r`;
  const r = await request.post(`${env.ORLA_SUPABASE_URL}/auth/v1/token?grant_type=password`, {
    headers: { apikey: env.ORLA_SUPABASE_PUBLISHABLE_KEY, "Content-Type": "application/json" },
    data: { email: creds("RESET").email, password: base },
  });
  return r.ok() ? { current: base, next: rotated } : { current: rotated, next: base };
}

test("AC-057 password reset revokes other sessions", async ({ browser, request }) => {
  const { current, next } = await currentResetPassword(request);
  await accessToken(request, "RESET", current);

  const other = await browser.newContext();
  const otherPage = await other.newPage();
  await login(otherPage, "RESET", current);

  const mine = await browser.newContext();
  const page = await mine.newPage();
  await login(page, "RESET", current);
  await page.goto("/reset-password");
  await page.getByLabel("New password", { exact: true }).fill(next);
  await page.getByLabel("Retype new password").fill(next);
  await page.getByRole("button", { name: /update|save|reset|change/i }).click();
  await expect(page.locator(".status-error")).toHaveCount(0);

  await otherPage.goto("/dashboard");
  await expect(otherPage).toHaveURL(/\/login/, { timeout: 30_000 });
  await page.goto("/dashboard");
  await expect(page).not.toHaveURL(/\/login/);
  await other.close();
  await mine.close();
});
