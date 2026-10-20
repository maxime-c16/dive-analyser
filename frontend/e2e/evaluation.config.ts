import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Isolated local fixture, mocked APIs, generated media; no account or server writes.
export default defineConfig({
  testDir: './tests',
  testMatch: 'evaluation-buffering.spec.ts',
  workers: 1,
  use: { baseURL: 'http://127.0.0.1:3021', trace: 'retain-on-failure' },
  projects: [
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
  ],
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 3021 --strictPort',
    cwd: path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'),
    url: 'http://127.0.0.1:3021/e2e/fixtures/evaluation-review.html',
    reuseExistingServer: false,
  },
})
