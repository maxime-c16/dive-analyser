import { useLayoutEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

type OverlayEntry = { scope: string; index: number | null; depth: number; document: string }

const documentId = Math.random().toString(36)

function browserIndex(): number | null {
  const index: unknown = window.history.state?.idx
  return typeof index === 'number' && Number.isSafeInteger(index) && index >= 0 ? index : null
}

export function useSessionHistory() {
  const location = useLocation()
  const navigate = useNavigate()
  const closing = useRef<string | null>(null)
  const scope = location.pathname + location.search + location.hash
  const marker = location.state?.sessionOverlay as OverlayEntry | undefined
  const entry = marker?.scope === scope ? marker : undefined

  useLayoutEffect(() => { closing.current = null }, [location.key])

  function change(patch: Record<string, unknown>, replace = false) {
    const { pathname, search, hash, state } = location
    const index = browserIndex()
    navigate({ pathname, search, hash }, {
      state: {
        ...state, ...patch,
        ...(!replace && { sessionOverlay: {
          scope, depth: (entry?.depth ?? 0) + 1, index: index === null ? null : index + 1, document: documentId,
        } }),
      },
      replace, preventScrollReset: true,
    })
  }

  function canPop(steps: number) {
    if (!entry || steps < 1 || steps > entry.depth) return false
    const index = browserIndex()
    if (index === null) return entry.document === documentId
    // React Router's index persists on reload. A single-entry duplicate or an
    // entry with copied state may have no reachable parent.
    return entry.index === index && index >= steps && window.history.length > steps
  }

  function goBack(steps: number, fallback: Record<string, unknown>) {
    if (closing.current === location.key) return
    closing.current = location.key
    if (canPop(steps)) navigate(-steps)
    else change(fallback, true)
  }

  function close(field: string) {
    const depth = Math.max(0, (entry?.depth ?? 0) - 1)
    goBack(1, { [field]: undefined, sessionOverlay: depth && entry ? { ...entry, depth, index: null, document: '' } : undefined })
  }

  function returnToBase() {
    if (!entry?.depth) return false
    goBack(entry.depth, { sessionViewer: undefined, sessionDownloadAccess: undefined, sessionOnboarding: undefined, sessionOverlay: undefined })
    return true
  }

  return { location, change, close, returnToBase }
}
