import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.DEADLOCK_E2E_PORT ?? 8765);
if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error("DEADLOCK_E2E_PORT must be a valid TCP port");
}
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  webServer: {
    command: `cd .. && DEADLOCK_PORT=${port} PYTHONPATH=backend uv run python -m deadlock.api`,
    url: `${baseURL}/api/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
