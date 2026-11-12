/** AC-073 — ORLA's answer matches the dashboard figure. PROTECTED. Needs OPENROUTER_API_KEY. */
import { test, expect } from "@playwright/test";
import { accessToken, api, login } from "./helpers";

function lastCompletedWeek(): { start: string; end: string } {
  const now = new Date();
  const day = (now.getUTCDay() + 6) % 7;
  const monday = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - day));
  const start = new Date(monday.getTime() - 7 * 86400000);
  const end = new Date(monday.getTime() - 86400000);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return { start: iso(start), end: iso(end) };
}

test("AC-073 answer matches dashboard figures", async ({ page, request }) => {
  const { token } = await accessToken(request, "OWNER");
  const businesses = await (await api(request, token, "GET", "/businesses")).json();
  const { start, end } = lastCompletedWeek();
  const fin = await (await api(request, token, "GET",
    `/businesses/${businesses[0].id}/analytics/financial-performance?start=${start}&end=${end}`)).json();
  const revenue = Number(fin.revenue.current);
  expect(revenue).toBeGreaterThan(0);
  const forms = [revenue.toFixed(2), revenue.toLocaleString("en-IE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })];

  await login(page, "OWNER");
  await page.goto("/chat");
  await page.getByPlaceholder("Ask a question about your business…").fill("What was my total revenue last week?");
  await page.getByRole("button", { name: /send|ask/i }).click();
  const answer = page.locator("main").getByText(new RegExp(forms.map((f) => f.replace(/[.,]/g, "\\$&")).join("|")));
  await expect(answer.first()).toBeVisible({ timeout: 45_000 });
});
