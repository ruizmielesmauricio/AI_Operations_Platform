/**
 * ORLA browser acceptance tests (acceptance/criteria.md, AC-019/032/043/050/056-058/071-073/076/077).
 * PROTECTED: the autobuild loop may not edit tests/acceptance-e2e/.
 *
 * Starts the real backend (fresh local Postgres e2e database, migrated) and
 * the real Next.js frontend, against the Supabase project + Stripe sandbox
 * configured in the repo-root .env.test.local (git-ignored).
 * JUnit results: progress/e2e-junit.xml (read by scripts/score.py).
 */
import { defineConfig, devices } from "@playwright/test";
import { loadTestEnv } from "./env";

const env = loadTestEnv();
const API_PORT = 8765;
const WEB_PORT = 3765;
const python = process.env.PYTHON || "python3";

export default defineConfig({
  testDir: ".",
  testMatch: /.*\.(spec|setup)\.ts$/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [["list"], ["junit", { outputFile: "../../progress/e2e-junit.xml" }]],
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "off",
    screenshot: "only-on-failure",
  },
  outputDir: "../../progress/e2e-artifacts",
  projects: [
    { name: "setup", testMatch: /global\.setup\.ts$/ },
    { name: "acceptance", testMatch: /.*\.spec\.ts$/, dependencies: ["setup"], use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: [
    {
      command: `${python} ../acceptance-e2e/seed.py reset && ${python} -m uvicorn app.main:app --port ${API_PORT}`,
      cwd: "../../backend",
      url: `http://localhost:${API_PORT}/health`,
      timeout: 180_000,
      reuseExistingServer: false,
      env: {
        ENVIRONMENT: "test",
        DATABASE_URL: env.ORLA_E2E_DATABASE_URL,
        ALLOWED_ORIGINS: `http://localhost:${WEB_PORT}`,
        APP_BASE_URL: `http://localhost:${WEB_PORT}`,
        SUPABASE_URL: env.ORLA_SUPABASE_URL,
        SUPABASE_ANON_KEY: env.ORLA_SUPABASE_PUBLISHABLE_KEY,
        STRIPE_SECRET_KEY: env.STRIPE_SECRET_KEY,
        STRIPE_PRICE_ID: env.ORLA_STRIPE_PRICE_ID,
        STRIPE_BRANCH_PRICE_ID: env.ORLA_STRIPE_BRANCH_PRICE_ID,
        STRIPE_EMPLOYEE_SEAT_PRICE_ID: env.ORLA_STRIPE_EMPLOYEE_SEAT_PRICE_ID,
        R2_ACCOUNT_ID: env.R2_ACCOUNT_ID,
        R2_ACCESS_KEY_ID: env.R2_ACCESS_KEY_ID,
        R2_SECRET_ACCESS_KEY: env.R2_SECRET_ACCESS_KEY,
        R2_BUCKET_NAME: env.R2_BUCKET_NAME,
        OPENROUTER_API_KEY: env.OPENROUTER_API_KEY,
      },
    },
    {
      command: `npm run dev -- --port ${WEB_PORT}`,
      cwd: "../../frontend",
      url: `http://localhost:${WEB_PORT}/login`,
      timeout: 240_000,
      reuseExistingServer: false,
      env: {
        NEXT_PUBLIC_API_URL: `http://localhost:${API_PORT}`,
        NEXT_PUBLIC_SUPABASE_URL: env.ORLA_SUPABASE_URL,
        NEXT_PUBLIC_SUPABASE_ANON_KEY: env.ORLA_SUPABASE_PUBLISHABLE_KEY,
      },
    },
  ],
});
