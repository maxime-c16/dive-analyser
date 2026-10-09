import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useLocation, useNavigationType } from 'react-router-dom'
import { hasOpenOverlay, useOverlayCount } from '../utils/overlays'
import { navPolicyFor, primaryTabFor, readTabContext, saveTabContext } from './mobileNavigation'
const actions = new Set<symbol>()
const listeners = new Set<() => void>()
export function useBottomAction(active: boolean) {
  useLayoutEffect(() => {
    if (!active) return
    const id = Symbol(); actions.add(id); listeners.forEach(f => f())
    return () => { actions.delete(id); listeners.forEach(f => f()) }
  }, [active])
}
export function isTextEntry(element: Element | null) {
  return element instanceof HTMLElement && (element.isContentEditable || element.matches('textarea, [contenteditable="true"], input:not([type="button"]):not([type="submit"]):not([type="reset"]):not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="file"]):not([type="color"]):not([type="hidden"])'))
}
/** Coarse-pointer focus is a conservative editing policy, not keyboard detection.
 * A physical keyboard or a dismissed software keyboard can retain focus. The
 * pills return on blur; viewport shrink also hides them without relying on focus.
 * Never use visualViewport.offsetTop (Safari can retain stale offsets).
 */
export function useMobileViewport() {
  const [value, setValue] = useState({ width: window.innerWidth, editing: false, height: window.visualViewport?.height ?? window.innerHeight })
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>
    const coarse = window.matchMedia?.('(pointer: coarse)')
    const update = () => {
      clearTimeout(timer)
      const viewport = window.visualViewport
      const shrink = !!viewport && viewport.scale === 1 && window.innerHeight - viewport.height > 150
      setValue({ width: window.innerWidth, editing: !!coarse?.matches && (isTextEntry(document.activeElement) || shrink), height: viewport?.height ?? window.innerHeight })
    }
    const blur = () => { clearTimeout(timer); timer = setTimeout(update, 150) }
    update()
    window.addEventListener('resize', update); window.visualViewport?.addEventListener('resize', update)
    document.addEventListener('focusin', update); document.addEventListener('focusout', blur); coarse?.addEventListener('change', update)
    return () => { clearTimeout(timer); window.removeEventListener('resize', update); window.visualViewport?.removeEventListener('resize', update); document.removeEventListener('focusin', update); document.removeEventListener('focusout', blur); coarse?.removeEventListener('change', update) }
  }, [])
  return value
}
export function useHasBottomAction() {
  return useSyncExternalStore(f => { listeners.add(f); return () => { listeners.delete(f) } }, () => actions.size > 0, () => false)
}
export function useMobileNavPolicy() {
  const location = useLocation()
  const viewport = useMobileViewport()
  const overlays = useOverlayCount()
  const bottomAction = useHasBottomAction()
  return navPolicyFor(location.pathname, viewport.width, { overlays, editing: viewport.editing, bottomAction, clip: new URLSearchParams(location.search).has('clip') })
}
export function useTabMemory(account: number | undefined) {
  const location = useLocation()
  const navigationType = useNavigationType()
  const active = useRef({ location, scroll: window.scrollY })
  const owner = useRef(account)
  const entries = useRef(new Map<string, number>())
  const restoring = useRef(false)
  useEffect(() => {
    if (!account) return
    const save = () => {
      if (hasOpenOverlay() || restoring.current) return
      const { location: loc } = active.current, tab = primaryTabFor(loc.pathname)
      if (tab && !new URLSearchParams(loc.search).has('clip')) {
        active.current.scroll = window.scrollY
        entries.current.set(loc.key, window.scrollY)
        saveTabContext(account, tab, { url: loc.pathname + loc.search + loc.hash, scroll: window.scrollY })
      }
    }
    window.addEventListener('scroll', save, { passive: true }); window.addEventListener('pagehide', save)
    return () => { window.removeEventListener('scroll', save); window.removeEventListener('pagehide', save) }
  }, [account])
  useLayoutEffect(() => {
    if (owner.current !== account) {
      entries.current.clear(); active.current = { location, scroll: 0 }; owner.current = account
    }
    const previous = active.current
    const previousTab = primaryTabFor(previous.location.pathname)
    if (account && previousTab && previous.location.key !== location.key && !new URLSearchParams(previous.location.search).has('clip')) {
      saveTabContext(account, previousTab, { url: previous.location.pathname + previous.location.search + previous.location.hash, scroll: previous.scroll })
      entries.current.set(previous.location.key, previous.scroll)
    }
    const tab = primaryTabFor(location.pathname)
    const clip = new URLSearchParams(location.search).has('clip')
    const leavingClip = new URLSearchParams(previous.location.search).has('clip') && previous.location.pathname === location.pathname
    const target = navigationType === 'POP' ? entries.current.get(location.key) : location.state?.mobileTabRestore
    active.current = { location, scroll: typeof target === 'number' ? target : window.scrollY }
    if (!account || !tab || clip || leavingClip) return
    saveTabContext(account, tab, { url: location.pathname + location.search + location.hash, scroll: active.current.scroll })
    if (typeof target !== 'number' || window.innerWidth >= 1024) return
    // Lazy routes/data may not have their final height at the first commit.
    // Stop as soon as the user takes control; POP uses the browser entry key.
    let stopped = false, frame = 0
    restoring.current = true
    const started = performance.now()
    const stop = () => { stopped = true; restoring.current = false; cancelAnimationFrame(frame) }
    const restore = () => {
      if (stopped) return
      window.scrollTo({ top: target, behavior: 'instant' })
      if (performance.now() - started < 2500 && window.scrollY + 1 < target) frame = requestAnimationFrame(restore)
      else stop()
    }
    frame = requestAnimationFrame(restore)
    window.addEventListener('wheel', stop, { passive: true }); window.addEventListener('touchstart', stop, { passive: true }); window.addEventListener('keydown', stop)
    return () => { stop(); window.removeEventListener('wheel', stop); window.removeEventListener('touchstart', stop); window.removeEventListener('keydown', stop) }
  }, [account, location.key, navigationType])
  return (tab: ReturnType<typeof primaryTabFor>) => account && tab ? readTabContext(account, tab) : null
}
