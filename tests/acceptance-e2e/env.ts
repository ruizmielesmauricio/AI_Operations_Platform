/** Loads repo-root .env.test.local (git-ignored) into a plain object. PROTECTED. */
import * as fs from "fs";
import * as path from "path";

export type TestEnv = Record<string, string>;

export function loadTestEnv(): TestEnv {
  const out: TestEnv = {};
  const file = path.resolve(__dirname, "../../.env.test.local");
  if (fs.existsSync(file)) {
    for (const raw of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
      const line = raw.trim();
      if (!line || line.startsWith("#") || !line.includes("=")) continue;
      const i = line.indexOf("=");
      out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
    }
  }
  for (const [k, v] of Object.entries(process.env)) {
    if (v !== undefined && (k.startsWith("ORLA_") || k.startsWith("STRIPE_") || k.startsWith("R2_") || k === "OPENROUTER_API_KEY")) {
      out[k] = v;
    }
  }
  out.ORLA_E2E_DATABASE_URL ||= "postgresql+psycopg://aiops:aiops_dev_password@localhost:5432/orla_e2e";
  return out;
}

export function required(env: TestEnv, ...keys: string[]): void {
  const missing = keys.filter((k) => !env[k]);
  if (missing.length) {
    throw new Error(`Missing test configuration (set in .env.test.local): ${missing.join(", ")}`);
  }
}
