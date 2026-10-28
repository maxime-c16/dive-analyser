/**
 * Per-tab serialization of session-mutating requests.
 *
 * Login, registration, invite redemption, claim redemption, password change
 * and logout each replace the HttpOnly session cookie. If a logout response
 * lands after a newer login response, the browser applies its cookie clearing
 * last and wipes the fresh session; the reverse order revokes the wrong
 * session. These requests must therefore never overlap in one tab: each one
 * runs only after the previous session mutation has settled.
 *
 * Read-only `/auth/me` refreshes stay outside the lock. They wait for a
 * pending logout instead of racing it, then perform a single fetch.
 */

let tail: Promise<void> = Promise.resolve()

/** Resolves when no session mutation is in flight. */
export function waitForSessionIdle(): Promise<void> {
  return tail
}

/**
 * Run `task` after all previously queued session mutations have settled.
 * A failing task never blocks the queue: the chain always resolves.
 */
export function runSessionMutation<T>(task: () => Promise<T>): Promise<T> {
  const run = tail.then(task, task)
  tail = run.then(
    () => undefined,
    () => undefined,
  )
  return run
}
