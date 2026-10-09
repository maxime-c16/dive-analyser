import { useLayoutEffect, type RefObject } from 'react'
import { useOverlayCount } from '../utils/overlays'
import { useHasBottomAction, useMobileViewport } from './useMobileNavigation'
const notices = new Map<HTMLElement, number>()
function publish() {
  let before = 0
  for (const [element, height] of notices) {
    element.style.setProperty('--mobile-notice-before', `${before}px`)
    before += height + 8
  }
  document.documentElement.style.setProperty('--mobile-notice-count', String(Math.max(1, notices.size)))
  document.documentElement.style.setProperty('--mobile-notice-offset', `${before ? before + 24 : 0}px`)
}
/** Notices outside Router share the shell's CSS reserve. On mobile they pause
 * behind a modal, during touch editing, or when page actions own the bottom.
 * Their state/cooldown is untouched. Multiple notice groups stack without overlap.
 */
export function useBottomNotice(ref: RefObject<HTMLElement>, enabled: boolean) {
  const { width, editing } = useMobileViewport()
  const overlays = useOverlayCount()
  const action = useHasBottomAction()
  const show = width >= 1024 || (!editing && !overlays && !action)
  useLayoutEffect(() => {
    if (width >= 1024 || !enabled || !show || !ref.current) return
    const element = ref.current
    const update = () => { notices.set(element, element.getBoundingClientRect().height); publish() }
    update()
    const observer = new ResizeObserver(update); observer.observe(element)
    return () => { observer.disconnect(); notices.delete(element); element.style.removeProperty('--mobile-notice-before'); publish() }
  }, [ref, enabled, show, width >= 1024])
  return show
}
