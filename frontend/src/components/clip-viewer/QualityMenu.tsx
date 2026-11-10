import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { Check, ChevronsUpDown } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import './qualityMenu.css'

export interface QualityOption {
  key: string
  label: string
}

/**
 * One quality control for every clip player: the trigger names the current
 * rendition (dot = reduced quality) and opens an explicit list. Keys handled
 * here never reach the viewer's own shortcuts (arrows, Escape).
 */
export default function QualityMenu({ options, current, reduced, onSelect, className = '' }: {
  options: QualityOption[]
  current: string
  reduced: boolean
  onSelect: (key: string) => void
  className?: string
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const menuId = useId()
  const currentLabel = options.find(option => option.key === current)?.label ?? options[0]?.label ?? ''

  useEffect(() => {
    if (!open) return
    const items = root.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]')
    const checked = root.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')
    ;(checked ?? items?.[0])?.focus()
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', outside, true)
    return () => document.removeEventListener('pointerdown', outside, true)
  }, [open])

  const close = (refocus: boolean) => {
    setOpen(false)
    if (refocus) trigger.current?.focus()
  }

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!open) return
    const items = [...(root.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]') ?? [])]
    const index = items.indexOf(document.activeElement as HTMLButtonElement)
    if (event.key === 'Escape') close(true)
    else if (event.key === 'ArrowDown') items[(index + 1) % items.length]?.focus()
    else if (event.key === 'ArrowUp') items[(index - 1 + items.length) % items.length]?.focus()
    else if (event.key === 'Tab') setOpen(false)
    else return
    if (event.key !== 'Tab') event.preventDefault()
    event.stopPropagation()
  }

  if (options.length < 2) {
    return <span className={`clip-quality-pill ${className}`}>
      <span className="sr-only">{t('videoPlayer.quality')}: </span>
      {reduced && <span className="clip-quality-dot" aria-hidden="true" />}<span>{currentLabel}</span>
    </span>
  }

  return <div ref={root} className={`clip-quality-menu ${className}`} onKeyDown={onKeyDown} onPointerDown={event => event.stopPropagation()}>
    <button
      ref={trigger}
      type="button"
      className="clip-quality-pill"
      aria-label={t('videoPlayer.changeQuality')}
      aria-haspopup="menu"
      aria-expanded={open}
      aria-controls={open ? menuId : undefined}
      onClick={() => setOpen(value => !value)}
    >
      {reduced && <span className="clip-quality-dot" aria-hidden="true" />}{currentLabel}<ChevronsUpDown size={14} aria-hidden="true" />
    </button>
    {open && <div id={menuId} role="menu" aria-label={t('videoPlayer.quality')} className="clip-quality-list">
      {options.map(option => <button
        key={option.key}
        type="button"
        role="menuitemradio"
        aria-checked={option.key === current}
        onClick={() => {
          close(true)
          if (option.key !== current) onSelect(option.key)
        }}
      >
        <span>{option.label}</span>
        {option.key === current && <Check size={15} aria-hidden="true" />}
      </button>)}
    </div>}
  </div>
}
