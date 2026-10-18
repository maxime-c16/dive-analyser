import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e/calendar",
  workers: 1,
  retries: 0,
  use: { baseURL: "http://127.0.0.1:5173", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: devices["Desktop Chrome"] }],
  outputDir: "/tmp/calendar-task03-tests",
  reporter: "list",
});
