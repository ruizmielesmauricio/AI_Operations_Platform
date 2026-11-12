/**
 * Runs once after both servers are up (Playwright "setup" project).
 * Fresh e2e database each run: the owner gets a coffee-shop business (paid,
 * seeded with two weeks of sales and a weekly report); the reset user gets an
 * unpaid bike shop; the onboarding user gets nothing (brand-new account).
 * PROTECTED.
 */
import { test as setup, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import * as path from "path";
import { accessToken, api } from "./helpers";

setup("seed e2e data", async ({ request }) => {
  const owner = await accessToken(request, "OWNER");
  const staff = await accessToken(request, "STAFF");
  const reset = await accessToken(request, "RESET");

  const cafe = await api(request, owner.token, "POST", "/businesses", {
    name: "ORLA E2E Cafe", template: "coffee_shop", timezone: "Europe/Dublin",
  });
  expect(cafe.status(), await cafe.text()).toBe(201);
  const unpaid = await api(request, reset.token, "POST", "/businesses", {
    name: "ORLA E2E Unpaid Shop", template: "bicycle_shop", timezone: "Europe/Dublin",
  });
  expect(unpaid.status(), await unpaid.text()).toBe(201);
  await api(request, staff.token, "GET", "/businesses");

  execFileSync(process.env.PYTHON || "python3", [path.join(__dirname, "seed.py"), "data", owner.userId, staff.userId], {
    stdio: "inherit",
  });
});
