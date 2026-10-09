import { defineConfig, devices } from '@playwright/test'
/** Fully local, development-only fixture; no auth/global setup/live backend. */
export default defineConfig({
  testDir:'./e2e/navigation', workers:1, retries:0, timeout:30000,
  webServer:{ command:'npm run dev -- --host 127.0.0.1 --port 5173 --strictPort', url:'http://127.0.0.1:5173/e2e/fixtures/navigation-review.html', reuseExistingServer:true },
  use:{ baseURL:'http://127.0.0.1:5173', screenshot:'only-on-failure', trace:'retain-on-failure' },
  projects:[{name:'chromium',use:{...devices['Desktop Chrome']}},{name:'webkit',use:{...devices['iPhone 13'],browserName:'webkit'}}],
  outputDir:'/tmp/mobile-pr2-playwright', reporter:'list',
})
