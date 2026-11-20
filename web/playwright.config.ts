import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against running servers (API on :8000 with ENV=dev and seed data,
 * web on :5173). Locally they use the installed Chrome (E2E_CHANNEL=chrome, default);
 * in CI run `npx playwright install chromium` and set E2E_CHANNEL= (empty).
 *
 *   npm run e2e
 */
const channel = process.env.E2E_CHANNEL ?? "chrome";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
    ignoreHTTPSErrors: true, // the dev server may use a self-signed certificate (E2E_BASE_URL=https://...)
    ...devices["Pixel 7"],
    ...(channel ? { channel } : {}),
  },
});
