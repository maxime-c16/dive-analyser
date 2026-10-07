/// <reference lib="webworker" />
/**
 * Push-only service worker (PR3 notifications-push).
 *
 * Built via vite-plugin-pwa `injectManifest` from this source. It handles
 * `push` (showNotification) and `notificationclick` (focus/open + navigate)
 * and nothing else: there is deliberately NO workbox precache, NO fetch
 * handler and NO runtime caching, so the existing offline/cache behaviour
 * of the app is unchanged. The payload shape mirrors the backend
 * push_service fan-out: {title, body, url}.
 */
export {}

const sw = self as unknown as ServiceWorkerGlobalScope

declare global {
  interface Window {
    // Build-time placeholder for vite-plugin-pwa `injectManifest` (the
    // build fails without the literal `self.__WB_MANIFEST` below).
    __WB_MANIFEST?: Array<{ url: string; revision: string | null }>
  }
}

// The precache manifest is intentionally NEVER consumed: no
// precacheAndRoute, no fetch handler, no runtime caching. This worker is
// push-only, so the app's existing offline/cache behaviour is unchanged.
// NOTE: the literal `self.__WB_MANIFEST` must survive bundling+minify
// (vite-plugin-pwa `injectManifest` fails the build without it). A bare
// read and a self-assignment are both dropped as side-effect-free, so the
// placeholder is explicitly discarded with `delete` — a real side effect
// the minifier must keep, and an honest no-op at runtime.
delete self.__WB_MANIFEST

type PushPayload = {
  title?: unknown
  body?: unknown
  url?: unknown
}

type PushEventLike = {
  data?: { json(): unknown } | null
  waitUntil(promise: Promise<unknown>): void
}

type NotificationEventLike = {
  notification: { close(): void; data?: unknown }
  waitUntil(promise: Promise<unknown>): void
}

const FALLBACK_TITLE = 'Dive Analyser'
const FALLBACK_URL = '/notifications'
const ICON = '/icons/icon-192.png'

function payloadUrl(value: unknown): string {
  return typeof value === 'string' && value.startsWith('/') ? value : FALLBACK_URL
}

sw.addEventListener('push', (rawEvent: Event) => {
  const event = rawEvent as unknown as PushEventLike
  let data: PushPayload = {}
  try {
    const parsed: unknown = event.data?.json()
    if (parsed && typeof parsed === 'object') data = parsed as PushPayload
  } catch {
    // Corrupt/empty payload: fall back to defaults below.
  }
  const title = typeof data.title === 'string' && data.title ? data.title : FALLBACK_TITLE
  const body = typeof data.body === 'string' ? data.body : ''
  const url = payloadUrl(data.url)
  event.waitUntil(
    sw.registration.showNotification(title, {
      body,
      icon: ICON,
      badge: ICON,
      data: { url },
    }),
  )
})

sw.addEventListener('notificationclick', (rawEvent: Event) => {
  const event = rawEvent as unknown as NotificationEventLike
  event.notification.close()
  const url = payloadUrl((event.notification.data as { url?: unknown } | null)?.url)
  event.waitUntil(
    (async () => {
      const windows = await sw.clients.matchAll({ type: 'window', includeUncontrolled: true })
      for (const candidate of windows) {
        const windowClient = candidate as WindowClient
        if (windowClient.url.startsWith(sw.location.origin)) {
          try {
            await windowClient.navigate(url)
          } catch {
            // Navigation is best-effort; focusing still helps.
          }
          await windowClient.focus()
          return
        }
      }
      await sw.clients.openWindow(url)
    })(),
  )
})
