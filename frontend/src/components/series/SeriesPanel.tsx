import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useModalOverlay } from '../../utils/overlays'

const MOBILE = '(max-width: 760px)'

export function useSeriesMobileLayout() {
  const [mobile, setMobile] = useState(() => window.matchMedia?.(MOBILE).matches ?? false)
  useEffect(() => {
    const query = window.matchMedia?.(MOBILE)
    if (!query) return
    const update = () => setMobile(query.matches)
    update()
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])
  return mobile
}

/** The same form stays in flow on desktop and becomes a focused mobile sheet. */
export default function SeriesPanel({ label, id, className, children, onClose, layer = 60 }: {
  label: string; id?: string; className: string; children: ReactNode; onClose: () => void; layer?: number
}) {
  const mobile = useSeriesMobileLayout()
  const container = useRef<HTMLElement>(null)
  useModalOverlay(container, { enabled: mobile, onClose, layer })
  const content = <section ref={container} id={id} tabIndex={mobile ? -1 : undefined}
    role={mobile ? 'dialog' : 'region'} aria-modal={mobile || undefined} aria-label={label}
    className={`${className}${mobile ? ' series-workspace series-mobile-panel' : ''}`}>
    {children}
  </section>
  return mobile ? createPortal(<div className="series-panel-backdrop" style={{ zIndex: layer }}
    onClick={e => { if (e.target === e.currentTarget) onClose() }}>{content}</div>, document.body) : content
}
