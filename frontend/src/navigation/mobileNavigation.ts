export type PrimaryTab = 'dives' | 'messages' | 'community' | 'evaluations' | 'calendar'
export function primaryTabFor(path: string): PrimaryTab | null {
  if (/^\/calendar(?:\/|$)/.test(path)) return 'calendar'
  if (/^\/dives(?:\/|$)/.test(path)) return 'dives'
  if (/^\/messages(?:\/|$)/.test(path)) return 'messages'
  if (/^\/(?:community|users)(?:\/|$)/.test(path)) return 'community'
  if (/^\/evaluations\/?$/.test(path)) return 'evaluations'
  return null
}
export function navPolicyFor(path: string, width: number, state: { overlays?: number; editing?: boolean; bottomAction?: boolean; clip?: boolean } = {}): 'visible' | 'hidden' | 'replaced' {
  if (width >= 1024 || /^\/(?:login|register|share)(?:\/|$)/.test(path) || state.overlays || state.editing || state.clip) return 'hidden'
  if (state.bottomAction || (width < 768 && /^\/messages\/[^/]+\/?$/.test(path))) return 'replaced'
  return 'visible'
}
export function withoutClip(path: string) {
  const url = new URL(path, 'https://local.invalid')
  url.searchParams.delete('clip')
  // A skip-link never benefits a restored tab: the fragment is cleared as
  // soon as it is clicked (router.tsx skipToMainContent), so tab memory must
  // not re-save or re-serve one — a surviving #main-content would replay the
  // fragment navigation on restore and steal focus from the endpoint the
  // restore intends (e.g. the Library card behind a clip viewer).
  if (url.hash === '#main-content') url.hash = ''
  return url.pathname + url.search + url.hash
}
export type TabContext = { url: string; scroll: number }
const key = (account: number, tab: PrimaryTab) => `mobile-nav:v1:${account}:${tab}`
export function readTabContext(account: number, tab: PrimaryTab): TabContext | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(key(account, tab)) || 'null')
    if (!value || typeof value.url !== 'string' || !value.url.startsWith('/') || value.url.startsWith('//') || primaryTabFor(value.url.split(/[?#]/)[0]) !== tab || !Number.isFinite(value.scroll) || value.scroll < 0) return null
    return { url: withoutClip(value.url), scroll: value.scroll }
  } catch { return null }
}
export function saveTabContext(account: number, tab: PrimaryTab, value: TabContext) {
  try { sessionStorage.setItem(key(account, tab), JSON.stringify({ ...value, url: withoutClip(value.url) })) } catch { /* Memory is optional in private/storage-denied browsing. */ }
}
