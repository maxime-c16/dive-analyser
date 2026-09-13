import { ensureAuthenticatedState } from './helpers/auth';

/**
 * Logs in once via the app's real session-auth endpoint and stores the
 * session cookie as the Playwright storageState used by every test project.
 */
export default async function globalSetup(): Promise<void> {
  await ensureAuthenticatedState();
}
