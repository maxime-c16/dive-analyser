/** Only navigation/draft recovery owned by this feature, never unrelated app
 * preferences. A confirmed signed-out response purges all previous owners. */
export function clearNavigationSession(account?: number) {
  try {
    const prefixes = ['mobile-nav:v1:', 'message-draft:v1:'].map(prefix => account === undefined ? prefix : `${prefix}${account}:`)
    for (const key of Object.keys(sessionStorage)) if (prefixes.some(prefix => key.startsWith(prefix))) sessionStorage.removeItem(key)
  } catch { /* Storage may be unavailable. */ }
}
