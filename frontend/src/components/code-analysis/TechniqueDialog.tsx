import { useEffect, useId, useRef, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'

export default function TechniqueDialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null)
  const heading = useId()
  const close = useRef(onClose)
  close.current = onClose
  const { t } = useTranslation()
  useEffect(() => {
    const dialog = ref.current!
    const previous = document.activeElement as HTMLElement | null
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    if (typeof dialog.showModal === 'function') dialog.showModal()
    else dialog.setAttribute('open', '')
    return () => {
      if (typeof dialog.close === 'function') dialog.close()
      document.body.style.overflow = overflow
      previous?.focus()
    }
  }, [])
  useEffect(() => { ref.current?.querySelector('h2')?.focus({ preventScroll: true }) }, [title])
  return <dialog ref={ref} className="th-dialog" aria-labelledby={heading} onCancel={e => { e.preventDefault(); close.current() }} onClick={e => { if (e.target === e.currentTarget) { const box = e.currentTarget.getBoundingClientRect(); if (e.clientX < box.left || e.clientX > box.right || e.clientY < box.top || e.clientY > box.bottom) close.current() } }}>
    <header className="th-dialog-header"><h2 id={heading} tabIndex={-1}>{title}</h2><button className="th-icon" aria-label={t('technique.close')} onClick={onClose}><X size={20} /></button></header>
    <div className="th-dialog-body">{children}</div>
  </dialog>
}
