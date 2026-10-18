import { defineConfig, devices } from "@playwright/test";
// Live calendar flows against a local backend on a DISPOSABLE database
// (see docs/design/calendar/TASK_03_RESULT.md). Never point at production.
export default defineConfig({
  testDir: "./e2e/calendar-live",
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  use: { baseURL: process.env.CALENDAR_LIVE_URL || "http://127.0.0.1:5174", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: devices["Desktop Chrome"] }],
  outputDir: "/tmp/calendar-task03-live",
  reporter: "list",
});
