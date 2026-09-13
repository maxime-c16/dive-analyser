import { request } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * Authenticated E2E session fixture.
 *
 * Credentials are supplied ONLY via the E2E_TEST_EMAIL / E2E_TEST_PASSWORD
 * environment variables at run time. They are never committed, never written
 * to any durable file, and the resulting session state lives under
 * playwright/.auth/ (gitignored). The login uses the application's normal
 * supported authentication mechanism (POST /api/v1/auth/login) — no auth
 * semantics are changed and no production bypass exists.
 */
export const authStatePath = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
  '..',
  'playwright',
  '.auth',
  'user.json',
);

export async function ensureAuthenticatedState(): Promise<void> {
  const email = process.env.E2E_TEST_EMAIL;
  const password = process.env.E2E_TEST_PASSWORD;
  if (!email || !password) {
    throw new Error(
      'E2E_TEST_EMAIL and E2E_TEST_PASSWORD must be set in the environment to run the authenticated E2E suite.',
    );
  }
  const baseURL = process.env.E2E_BASE_URL || 'https://192.168.1.57:6443';
  fs.mkdirSync(path.dirname(authStatePath), { recursive: true });
  const context = await request.newContext({
    baseURL,
    ignoreHTTPSErrors: true,
  });
  try {
    const response = await context.post('/api/v1/auth/login', {
      data: { email, password, remember_me: true },
    });
    if (!response.ok()) {
      throw new Error(
        `E2E login failed with status ${response.status()} — check E2E_TEST_EMAIL/E2E_TEST_PASSWORD.`,
      );
    }
    await context.storageState({ path: authStatePath });
  } finally {
    await context.dispose();
  }
}
