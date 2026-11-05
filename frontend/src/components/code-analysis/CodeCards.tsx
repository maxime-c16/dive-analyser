import React, { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useLocation } from 'react-router-dom'
import { format, parseISO } from 'date-fns'
import { ChevronRight } from 'lucide-react'
import DiveThumbnail from '../DiveThumbnail'
import { diveCodeName } from '../../i18n/diveNames'
import { appLocale } from '../../utils/dateLocale'
import { performanceLabel, type Attempt } from '../../utils/attemptPresentation'
import type { CodeSummary } from '../../services/codeSummariesApi'
import { RatingBar, TrendBadge } from './parts'
import { fmtScore } from '../../utils/codeStats'

export type CodeSort = 'recent' | 'volume' | 'progress'

function sortCodes(codes: CodeSummary[], sort: CodeSort) {
  if (sort === 'volume') return [...codes].sort((a, b) => b.attempt_count - a.attempt_count)
  if (sort === 'progress') return [...codes].sort((a, b) => (b.trend?.delta ?? -99) - (a.trend?.delta ?? -99))
  return codes
}

/**
 * Library › par code: one card per code over the whole filtered Library.
 * The card opens the code's analysis; its thumbnail and score chips open
 * the clip in the viewer, as before.
 */
export default function CodeCards({ codes, sort, onSort, onOpenClip, diverId }: {
  codes: CodeSummary[]
  sort: CodeSort
  onSort: (sort: CodeSort) => void
  onOpenClip: (id: number) => void
  /** Another member's diver: cards open that diver's read-only analysis, and back returns here. */
  diverId?: number
}) {
  const { t, i18n } = useTranslation()
  const lang = i18n.language?.startsWith('fr') ? 'fr' : 'en'
  const location = useLocation()
  const ordered = useMemo(() => sortCodes(codes, sort), [codes, sort])
  const date = (value: string, pattern: string) => format(parseISO(value), pattern, { locale: appLocale() })
  return <div className="ca">
    <div className="ca-scroll" role="group" aria-label={t('codeAnalysis.sortAria')} style={{ marginBottom: 12 }}>
      {(['recent', 'volume', 'progress'] as const).map(option => <button key={option} type="button" className="ca-pill" aria-pressed={sort === option} onClick={() => onSort(option)}>{t(`codeAnalysis.sort.${option}`)}</button>)}
    </div>
    <div className="ca-code-grid">
      {ordered.map((code, index) => {
        const name = diveCodeName(code.dive_code, lang)
        const analysisHref = `/dives/analysis/${encodeURIComponent(code.dive_code)}${diverId ? `?diver=${diverId}` : ''}`
        const analysisState = diverId ? {codeDiverOpened:true,fromProfile:true} : {returnTo:`${location.pathname}${location.search}`}
        return <article key={code.dive_code} className="ca-code-card" style={{ '--i': Math.min(index, 12) } as React.CSSProperties}>
          <div className="ca-code-top">
            <button type="button" className="ca-thumb" aria-label={t('dives.openLatestAttempt', { code: code.dive_code })}
              onClick={event => { event.stopPropagation(); onOpenClip(code.latest.id) }}>
              <DiveThumbnail dive={code.latest as Attempt} compact />
            </button>
            <div style={{ minWidth: 0 }}>
              <div className="ca-code-code">{code.dive_code}</div>
              {name !== code.dive_code && <div className="ca-code-name">{name}</div>}
              {code.analytics && <div className="ca-code-stats">
                <span>{t('dives.avg')} <b>{fmtScore(code.average)}</b></span>
              </div>}
            </div>
            <div className="ca-code-side">{code.analytics && <TrendBadge delta={code.trend?.delta} />}<Link className="ca-code-analysis" to={analysisHref} state={analysisState} aria-label={t('codeAnalysis.openCode',{code:code.dive_code})}>{t('clipViewer.analysis')}<ChevronRight size={14} aria-hidden="true" /></Link></div>
          </div>
          <div className="ca-code-meta">
            <span>{t('codeAnalysis.attemptCount', { count: code.attempt_count })} · {t('codeAnalysis.sessionCount', { count: code.session_count })}</span>
            <span>{t('dives.last')} {date(code.last_attempt_at, 'd MMM')}</span>
          </div>
          <details className="ca-code-details" onClick={event => event.stopPropagation()} onKeyDown={event => event.stopPropagation()}>
          <summary>{t('dives.recentAttemptsFor', { code: code.dive_code })}</summary>
          {code.analytics && <div className="ca-code-stats">
            <span>{t('codeAnalysis.median')} <b>{fmtScore(code.median)}</b></span>
            <span>{t('dives.best')} <b>{fmtScore(code.best)}</b></span>
          </div>}
          <RatingBar ratings={code.ratings} />
          <dl className="ca-rating-legend">{(['P','G','M','B','F'] as const).filter(rating => code.ratings[rating]).map(rating => <div key={rating}><dt>{performanceLabel(rating)}</dt><dd>{code.ratings[rating]}</dd></div>)}</dl>
          <ul className="ca-recent-attempts" aria-label={t('dives.recentAttemptsFor',{code:code.dive_code})}>
            {code.recent.map(item => <li key={item.id}><button type="button" data-attempt-id={item.id} aria-label={t('dives.openAttemptFrom',{code:code.dive_code,date:date(item.dive_datetime,'d MMM HH:mm')})} onClick={() => onOpenClip(item.id)}><time dateTime={item.dive_datetime}>{date(item.dive_datetime,'d MMM HH:mm')}</time><small>#{item.id}</small><b>{fmtScore(item.score)} / 10</b><ChevronRight size={14} aria-hidden="true" /></button></li>)}
          </ul>
          </details>
        </article>
      })}
    </div>
  </div>
}
