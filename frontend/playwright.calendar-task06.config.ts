import { defineConfig, devices } from "@playwright/test";
// Disposable backend only. Seed instructions/evidence: TASK_06_RESULT.md.
export default defineConfig({
  testDir: "./e2e/calendar-live", testMatch: "task06.spec.ts", workers: 1, retries: 0,
  timeout: 120_000, expect: { timeout: 15_000 },
  use: { baseURL: process.env.CALENDAR_LIVE_URL || "http://127.0.0.1:5174", trace: "off" },
  projects: [{ name: "chromium", use: devices["Desktop Chrome"] }],
  outputDir: "/tmp/calendar-task06-live", reporter: "list",
});
