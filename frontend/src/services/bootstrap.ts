/**
 * One-shot seeds from GET /api/v1/bootstrap.
 *
 * When a session starts, AuthContext reads identity plus the shell widgets'
 * first payloads in one request. Each widget takes its seed once, on mount,
 * instead of firing its own first request; later polls use the normal routes.
 * Seeds are scoped to the account and expire quickly, so a stale or foreign
 * seed is never shown: a widget that finds none simply fetches as before.
 */

export type BootstrapSection = 'messages_unread' | 'notifications' | 'achievements_unseen' | 'updates'

const FRESH_MS = 10_000

let seed: { userId: number; at: number; sections: Partial<Record<BootstrapSection, unknown>> } | null = null

export function storeBootstrapSeed(userId: number, body: Record<string, unknown>): void {
  const sections: Partial<Record<BootstrapSection, unknown>> = {}
  for (const name of ['messages_unread', 'notifications', 'achievements_unseen', 'updates'] as const) {
    if (body[name] && typeof body[name] === 'object') sections[name] = body[name]
  }
  seed = { userId, at: Date.now(), sections }
}

/** The section's payload, at most once per session start; undefined otherwise. */
export function takeBootstrapSeed<T>(section: BootstrapSection, userId: number): T | undefined {
  if (!seed || seed.userId !== userId || Date.now() - seed.at > FRESH_MS) return undefined
  const value = seed.sections[section]
  delete seed.sections[section]
  return value as T | undefined
}

export function clearBootstrapSeed(): void {
  seed = null
}
