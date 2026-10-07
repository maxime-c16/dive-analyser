/**
 * Web Push device opt-in primitives (PR3 notifications-push).
 *
 * Browser-only helpers around the service worker (`sw-push.js`, built from
 * src/sw-push.ts) and the Push API. Permission is requested ONLY inside
 * `enablePushDevice`, which the UI calls from an explicit click handler —
 * never at login, never on first render.
 */
import {
  deletePushSubscription,
  savePushSubscription,
} from './notificationsApi'

export const PUSH_SW_URL = '/sw-push.js'

/**
 * The browser Navigator when present. Read via `window.navigator` (never a
 * bare `navigator` global) so SSR/test environments without that binding
 * stay safe — `typeof window` guards never throw.
 */
function getNavigator(): Navigator | undefined {
  if (typeof window === 'undefined') return undefined
  return window.navigator ?? undefined
}

/** True when this browser can do Web Push at all. */
export function pushSupported(): boolean {
  if (typeof window === 'undefined') return false
  const nav = getNavigator()
  if (!nav) return false
  return (
    'serviceWorker' in nav &&
    'PushManager' in window &&
    'Notification' in window
  )
}

/** True on iOS/iPadOS devices, where push needs an installed PWA (16.4+). */
export function isIosDevice(): boolean {
  const ua = getNavigator()?.userAgent || ''
  return /iPhone|iPad|iPod/i.test(ua)
}

/** Short human label for "this device" (stored server-side, ≤100 chars). */
export function defaultDeviceLabel(): string {
  try {
    const nav = getNavigator()
    if (!nav) return 'this device'
    if (nav.platform) return nav.platform.slice(0, 100)
    const ua = nav.userAgent || ''
    for (const token of ['iPhone', 'iPad', 'Android', 'Macintosh', 'Windows', 'Linux']) {
      if (ua.includes(token)) return token
    }
    return ua.slice(0, 60) || 'this device'
  } catch {
    return 'this device'
  }
}

/** VAPID public key (URL-safe base64) → Uint8Array for PushManager. */
export function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4)
  const raw = window.atob(base64.replace(/-/g, '+').replace(/_/g, '/') + padding)
  const output = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i += 1) output[i] = raw.charCodeAt(i)
  return output
}

/**
 * Existing push subscription for this device, if the SW is registered and
 * subscribed. Resolves null when anything is missing (never rejects).
 */
export async function getExistingPushSubscription(): Promise<PushSubscription | null> {
  try {
    if (!pushSupported()) return null
    const nav = getNavigator()
    if (!nav?.serviceWorker) return null
    const registration = await nav.serviceWorker.getRegistration(PUSH_SW_URL)
    if (!registration) return null
    return await registration.pushManager.getSubscription()
  } catch {
    return null
  }
}

export type EnablePushResult = { endpoint: string; alreadySubscribed: boolean }

/**
 * Full opt-in flow. Must be called from a user gesture: it registers the
 * push service worker, requests notification permission, subscribes with
 * the VAPID public key and stores the endpoint server-side.
 *
 * Throws Error('push-unsupported') | Error('permission-denied') |
 * Error('push-failed') so the UI can map to i18n strings.
 */
export async function enablePushDevice(publicKey: string): Promise<EnablePushResult> {
  if (!pushSupported() || !publicKey) throw new Error('push-unsupported')
  const nav = getNavigator()
  if (!nav?.serviceWorker) throw new Error('push-unsupported')
  const registration = await nav.serviceWorker.register(PUSH_SW_URL)
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') throw new Error('permission-denied')
  let subscription = await registration.pushManager.getSubscription()
  let alreadySubscribed = false
  if (subscription) {
    alreadySubscribed = true
  } else {
    try {
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey),
      })
    } catch {
      throw new Error('push-failed')
    }
  }
  if (!subscription) throw new Error('push-failed')
  const serialized = subscription.toJSON()
  const p256dh = serialized.keys?.p256dh
  const auth = serialized.keys?.auth
  if (!p256dh || !auth) throw new Error('push-failed')
  try {
    await savePushSubscription({
      endpoint: subscription.endpoint,
      keys: { p256dh, auth },
      device_label: defaultDeviceLabel(),
    })
  } catch {
    throw new Error('push-failed')
  }
  return { endpoint: subscription.endpoint, alreadySubscribed }
}

/**
 * Opt-out flow: unsubscribe this device and delete its server-side
 * endpoint. Resolves true when an endpoint was removed.
 */
export async function disablePushDevice(): Promise<boolean> {
  try {
    if (!pushSupported()) return false
    const nav = getNavigator()
    if (!nav?.serviceWorker) return false
    const registration = await nav.serviceWorker.getRegistration(PUSH_SW_URL)
    if (!registration) return false
    const subscription = await registration.pushManager.getSubscription()
    if (!subscription) return false
    const endpoint = subscription.endpoint
    try {
      await subscription.unsubscribe()
    } catch {
      // Unsubscribe is best-effort; the server-side delete below is what
      // actually stops pushes to this device.
    }
    try {
      await deletePushSubscription(endpoint)
    } catch {
      return false
    }
    return true
  } catch {
    return false
  }
}
