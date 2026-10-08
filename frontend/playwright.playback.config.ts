import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir: './e2e/tests', testMatch: 'progressivePlayback.spec.ts',
  workers: 1, timeout: 45_000, expect: { timeout: 15_000 },
  use: { baseURL: process.env.PLAYBACK_BASE_URL || 'http://127.0.0.1:3000', trace: 'retain-on-failure' },
  projects: [
    { name: 'webkit-desktop', use: { ...devices['Desktop Safari'] } },
    { name: 'webkit-mobile', use: { ...devices['iPhone 13'] } },
  ],
  reporter: [['list'], ['json', { outputFile: 'test-results/playback-results.json' }]],
  outputDir: 'test-results/playback',
})
