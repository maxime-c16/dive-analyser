import { scoreNumber } from '../evaluation/scoreFormatting'
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
  history,
  disabled = false,
}: {
  history?: { total: number; previous: boolean; next: boolean; loading: boolean; onPrevious: () => void; onNext: () => void }
  disabled?: boolean
  attempt: Attempt
  attempts: Attempt[]
  onSelect: (attempt: Attempt) => void
}) {
  const { t, i18n } = useTranslation()
  const day = attempt.dive_datetime.slice(0, 10)
  const items = useMemo(() => history ? attempts : attempts.filter((item) => item.dive_datetime.slice(0, 10) === day), [attempts, day, Boolean(history)])
  const listRef = useRef<HTMLOListElement>(null)
  useEffect(() => {
    const current = listRef.current?.querySelector<HTMLElement>('[aria-current="true"]')
    current?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  }, [attempt.id])
  if (!history && items.length < 2) return null
  return (
    <nav className={`clip-filmstrip${history ? ' is-history' : ''}`} aria-label={t(history ? 'technique.codeHistory' : 'clipViewer.sameDay')}>
      <p className="clip-filmstrip-day">
        <span>{history ? t('technique.codeHistory') : attemptDate(attempt, 'EEEE d MMMM')}</span>
        <span>{history ? t('technique.loadedClips', { loaded: items.length, total: history.total }) : items.length}</span>
      </p>
      {history && <div className="clip-filmstrip-controls">{history?.previous && <button className="clip-filmstrip-paging" disabled={disabled || history.loading} onClick={history.onPrevious}>{t('technique.earlierClips')}</button>}{history?.next && <button className="clip-filmstrip-paging" disabled={disabled || history.loading} onClick={history.onNext}>{t('technique.laterClips')}</button>}</div>}
      <ol ref={listRef}>
        {items.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              disabled={disabled}
              aria-current={item.id === attempt.id ? 'true' : undefined}
              aria-label={history ? attemptDate(item, 'd MMM yyyy · HH:mm') : t('clipViewer.openFromStrip', { code: item.dive_code, score: scoreNumber(attemptScore(item), i18n.language) })}
              onClick={() => item.id !== attempt.id && onSelect(item)}
            >
              <span className="clip-filmstrip-thumb"><DiveThumbnail dive={item} compact /></span>
              <span className="clip-filmstrip-code">{history ? attemptDate(item, 'd MMM') : item.dive_code}</span>
              <span className="clip-filmstrip-height">{history ? attemptDate(item, 'HH:mm') : item.height}</span>
              <span className="clip-filmstrip-score">{scoreNumber(attemptScore(item), i18n.language)}</span>
            </button>
          </li>
        ))}
      </ol>
    </nav>
  )
}
