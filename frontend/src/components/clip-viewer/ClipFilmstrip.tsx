import { useEffect, useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import type { Attempt } from '../../utils/attemptPresentation'
import { attemptDate, attemptScore } from '../../utils/attemptPresentation'
import DiveThumbnail from '../DiveThumbnail'

/**
 * The dives of the same day as the open one, in the list order: a column
 * beside the video on wide screens, a row under it on tablets. One click
 * jumps to any attempt of the session instead of N × Next.
 */
export default function ClipFilmstrip({
  attempt,
  attempts,
  onSelect,
}: {
  attempt: Attempt
  attempts: Attempt[]
  onSelect: (attempt: Attempt) => void
}) {
  const { t } = useTranslation()
  const day = attempt.dive_datetime.slice(0, 10)
  const items = useMemo(() => attempts.filter((item) => item.dive_datetime.slice(0, 10) === day), [attempts, day])
  const listRef = useRef<HTMLOListElement>(null)
  useEffect(() => {
    const current = listRef.current?.querySelector<HTMLElement>('[aria-current="true"]')
    current?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  }, [attempt.id])
  if (items.length < 2) return null
  return (
    <nav className="clip-filmstrip" aria-label={t('clipViewer.sameDay')}>
      <p className="clip-filmstrip-day">
        <span>{attemptDate(attempt, 'EEEE d MMMM')}</span>
        <span>{items.length}</span>
      </p>
      <ol ref={listRef}>
        {items.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              aria-current={item.id === attempt.id ? 'true' : undefined}
              aria-label={t('clipViewer.openFromStrip', { code: item.dive_code, score: attemptScore(item).toFixed(1) })}
              onClick={() => item.id !== attempt.id && onSelect(item)}
            >
              <span className="clip-filmstrip-thumb"><DiveThumbnail dive={item} compact /></span>
              <span className="clip-filmstrip-code">{item.dive_code}</span>
              <span className="clip-filmstrip-height">{item.height}</span>
              <span className="clip-filmstrip-score">{attemptScore(item).toFixed(1)}</span>
            </button>
          </li>
        ))}
      </ol>
    </nav>
  )
}
