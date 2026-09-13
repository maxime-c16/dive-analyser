import { ensureAuthenticatedState } from './helpers/auth';

/**
 * Logs in once via the app's real session-auth endpoint and stores the
 * session cookie as the Playwright storageState used by every test project.
 *
 * If runtime credentials are not present in this environment but a previous
 * authenticated storageState already exists, it is reused as-is: the session
 * itself is still the real authenticated mechanism, and nothing about
 * production auth changes.
 */
export default async function globalSetup(): Promise<void> {
  await ensureAuthenticatedState();
}
