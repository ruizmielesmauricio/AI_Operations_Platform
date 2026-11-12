/** Shared browser-test helpers. PROTECTED. */
import { expect, type Page, type APIRequestContext } from "@playwright/test";
import { loadTestEnv, required } from "./env";

export const env = loadTestEnv();
export const API = "http://localhost:8765";

export type Who = "OWNER" | "STAFF" | "RESET" | "ONBOARD";

export function creds(who: Who): { email: string; password: string } {
  required(env, `ORLA_TEST_${who}_EMAIL`, `ORLA_TEST_${who}_PASSWORD`);
  return { email: env[`ORLA_TEST_${who}_EMAIL`], password: env[`ORLA_TEST_${who}_PASSWORD`] };
}

/** Logs in through the real login form. */
export async function login(page: Page, who: Who, password?: string): Promise<void> {
  const c = creds(who);
  await page.goto("/login");
  await page.getByLabel("Email").fill(c.email);
  await page.getByLabel("Password", { exact: true }).fill(password ?? c.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).not.toHaveURL(/\/login(\?|$)/, { timeout: 20_000 });
}

/** A Supabase access token via the password grant (for API-level setup only). */
export async function accessToken(request: APIRequestContext, who: Who, password?: string): Promise<{ token: string; userId: string }> {
  required(env, "ORLA_SUPABASE_URL", "ORLA_SUPABASE_PUBLISHABLE_KEY");
  const c = creds(who);
  const r = await request.post(`${env.ORLA_SUPABASE_URL}/auth/v1/token?grant_type=password`, {
    headers: { apikey: env.ORLA_SUPABASE_PUBLISHABLE_KEY, "Content-Type": "application/json" },
    data: { email: c.email, password: password ?? c.password },
  });
  expect(r.ok(), `Supabase login for ${who} failed: ${r.status()}`).toBeTruthy();
  const body = await r.json();
  return { token: body.access_token, userId: body.user.id };
}

export async function api(request: APIRequestContext, token: string, method: string, path: string, data?: unknown) {
  return request.fetch(`${API}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    data: data === undefined ? undefined : JSON.stringify(data),
  });
}

export const BIKE_WORDS = /\b(bikes?|bicycles?|cycling|mechanics?|repairs?|workshop)\b/i;
