import { useLayoutEffect, useRef, useSyncExternalStore, type RefObject } from 'react'
import { isVisible, trapTabKey } from './a11y'

/** One document-wide owner, including portals and surfaces outside the router.
 * Layers match existing visual z-indexes; a sheet belongs above its viewer.
 * Only the top entry owns isolation/keyboard/focus. Scroll is locked until
 * the last entry leaves, even if a parent unmounts before its child.
 */
type Entry = {
  container: HTMLElement
  focus: HTMLElement
  extras: HTMLElement[]
  initialFocus: HTMLElement | null
  layer: number
  close: () => void
  restore: HTMLElement | null
  fallback: () => HTMLElement | null
}
const stack: Entry[] = []
const subscribers = new Set<() => void>()
let inertValues = new Map<Element, string | null>()
let scrollStyles: Array<[HTMLElement, string, string]> = []
let observer: MutationObserver | null = null
let revision = 0
const top = () => stack[stack.length - 1]
export const hasOpenOverlay = () => stack.length > 0
export const isTopOverlay = (element: HTMLElement | null) => !!element && top()?.focus === element
const publish = () => subscribers.forEach(listener => listener())
export function useOverlayCount() {
  return useSyncExternalStore(listener => { subscribers.add(listener); return () => { subscribers.delete(listener) } }, () => stack.length, () => 0)
}
function restoreInert() {
  for (const [element, value] of inertValues) {
    if (value === null) element.removeAttribute('inert')
    else element.setAttribute('inert', value)
  }
  inertValues = new Map()
}
function isolate() {
  restoreInert()
  const entry = top()
  if (!entry) return
  const paths = new Set<Element>()
  for (const island of [entry.container, ...entry.extras]) {
    let node: Element | null = island
    while (node) { paths.add(node); node = node.parentElement }
  }
  const visit = (parent: Element) => {
    for (const child of Array.from(parent.children)) {
      if (paths.has(child)) {
        if (child !== entry.container && !entry.extras.includes(child as HTMLElement)) visit(child)
      } else {
        inertValues.set(child, child.getAttribute('inert'))
        child.setAttribute('inert', '')
      }
    }
  }
  visit(document.body)
}
function reachable(element: HTMLElement | null): element is HTMLElement {
  return !!element?.isConnected && element !== document.body && isVisible(element) && !element.closest('[inert], [hidden]') && !element.matches(':disabled')
}
function enter(entry: Entry) {
  entry.focus.focus({ preventScroll: true })
}
function keyboard(event: KeyboardEvent) {
  const entry = top()
  if (!entry) return
  if (event.key === 'Escape' && !event.defaultPrevented) {
    event.preventDefault()
    event.stopImmediatePropagation()
    if (!event.repeat) entry.close()
  } else if (event.key === 'Tab') {
    trapTabKey(entry.focus, event)
    // Legacy document shortcuts must not also trap a lower surface.
    event.stopImmediatePropagation()
  }
}
function focusIn(event: FocusEvent) {
  const entry = top()
  if (entry && !entry.focus.contains(event.target as Node)) enter(entry)
}
function register(entry: Entry) {
  revision += 1
  if (!stack.length) {
    scrollStyles = [document.documentElement, document.body].map(element => [element, element.style.getPropertyValue('overflow'), element.style.getPropertyPriority('overflow')])
    for (const [element] of scrollStyles) element.style.setProperty('overflow', 'hidden')
    document.addEventListener('keydown', keyboard)
    document.addEventListener('focusin', focusIn, true)
    observer = new MutationObserver(isolate)
    observer.observe(document.body, { childList: true, subtree: true })
  }
  stack.push(entry)
  stack.sort((a, b) => a.layer - b.layer)
  isolate()
  if (top() === entry) {
    if (reachable(entry.initialFocus) && entry.focus.contains(entry.initialFocus)) entry.initialFocus.focus({ preventScroll: true })
    else enter(entry)
  }
  publish()
  return () => {
    const wasTop = top() === entry
    const index = stack.indexOf(entry)
    if (index < 0) return
    stack.splice(index, 1)
    // If a parent disappears first, children return to its original trigger.
    for (const child of stack) if (child.restore && entry.container.contains(child.restore)) child.restore = entry.restore
    isolate()
    if (!stack.length) {
      observer?.disconnect(); observer = null
      document.removeEventListener('keydown', keyboard)
      document.removeEventListener('focusin', focusIn, true)
      for (const [element, value, priority] of scrollStyles) {
        if (value) element.style.setProperty('overflow', value, priority)
        else element.style.removeProperty('overflow')
      }
      scrollStyles = []
    }
    const closedAt = wasTop ? ++revision : revision
    if (wasTop) {
      // React may restore the pre-commit selection after layout cleanups.
      // Restore only after that commit; a newer registration/close wins.
      queueMicrotask(() => {
        if (revision !== closedAt) return
        const parent = top()
        const origin = reachable(entry.restore) ? entry.restore : entry.fallback()
        if (reachable(origin) && (!parent || parent.focus.contains(origin))) origin.focus({ preventScroll: true })
        else if (parent) enter(parent)
      })
    }
    publish()
  }
}

type Options = {
  enabled?: boolean
  onClose: () => void
  layer?: number
  isolationRef?: RefObject<HTMLElement>
  extraRef?: RefObject<HTMLElement>
  initialFocus?: () => HTMLElement | null
  /** Known opener (e.g. Safari does not focus buttons on pointer clicks). */
  returnFocus?: () => HTMLElement | null
  /** Used when the opener unmounted or is no longer reachable. */
  fallbackFocus?: () => HTMLElement | null
}
/** Call unconditionally; refs must be mounted when enabled. Callback changes
 * never reorder the stack or reset the captured trigger. */
export function useModalOverlay(ref: RefObject<HTMLElement>, options: Options) {
  const enabled = options.enabled ?? true
  const latest = useRef(options)
  latest.current = options
  const origin = useRef<HTMLElement | null>(null)
  const active = useRef(false)
  if (enabled && !active.current) origin.current = document.activeElement as HTMLElement | null
  active.current = enabled
  useLayoutEffect(() => {
    if (!enabled || !ref.current) return
    return register({
      container: latest.current.isolationRef?.current || ref.current,
      focus: ref.current,
      extras: latest.current.extraRef?.current ? [latest.current.extraRef.current] : [],
      initialFocus: latest.current.initialFocus?.() ?? null,
      layer: latest.current.layer ?? 50,
      close: () => latest.current.onClose(),
      restore: latest.current.returnFocus?.() ?? origin.current,
      fallback: () => latest.current.fallbackFocus?.() ?? document.getElementById('main-content'),
    })
  }, [enabled, ref])
}
