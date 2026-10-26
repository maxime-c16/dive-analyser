import React, { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate } from 'react-router-dom'
import { format, parseISO } from 'date-fns'
import { ChevronRight } from 'lucide-react'
import DiveThumbnail from '../DiveThumbnail'
import { diveCodeName } from '../../i18n/diveNames'
import { appLocale } from '../../utils/dateLocale'
import type { Attempt } from '../../utils/attemptPresentation'
import type { CodeSummary } from '../../services/codeSummariesApi'
import { RatingBar, ScoreChip, Sparkline, TrendBadge } from './parts'
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
  const navigate = useNavigate()
  const location = useLocation()
  const ordered = useMemo(() => sortCodes(codes, sort), [codes, sort])
  const open = (code: string) => diverId
    ? navigate(`/dives/analysis/${encodeURIComponent(code)}?diver=${diverId}`, { state: { codeDiverOpened: true, fromProfile: true } })
    : navigate(`/dives/analysis/${encodeURIComponent(code)}`, { state: { returnTo: `${location.pathname}${location.search}` } })
  const date = (value: string, pattern: string) => format(parseISO(value), pattern, { locale: appLocale() })
  return <div className="ca">
    <div className="ca-scroll" role="group" aria-label={t('codeAnalysis.sortAria')} style={{ marginBottom: 12 }}>
      {(['recent', 'volume', 'progress'] as const).map(option => <button key={option} type="button" className="ca-pill" aria-pressed={sort === option} onClick={() => onSort(option)}>{t(`codeAnalysis.sort.${option}`)}</button>)}
    </div>
    <div className="ca-code-grid">
      {ordered.map((code, index) => {
        const name = diveCodeName(code.dive_code, lang)
        return <div key={code.dive_code} role="link" tabIndex={0} className="ca-code-card ca-pop" style={{ '--i': Math.min(index, 12) } as React.CSSProperties}
          aria-label={t('codeAnalysis.openCode', { code: code.dive_code })}
          onClick={() => open(code.dive_code)}
          onKeyDown={event => { if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); open(code.dive_code) } }}>
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
                <span>{t('codeAnalysis.median')} <b>{fmtScore(code.median)}</b></span>
                <span>{t('dives.best')} <b>{fmtScore(code.best)}</b></span>
              </div>}
            </div>
            {code.analytics && <div className="ca-code-side"><TrendBadge delta={code.trend?.delta} /><Sparkline values={code.spark} /></div>}
          </div>
          <div className="ca-code-meta">
            <span>{t('codeAnalysis.attemptsSessions', { attempts: code.attempt_count, sessions: code.session_count })}</span>
            <span>{t('dives.last')} {date(code.last_attempt_at, 'd MMM')}</span>
          </div>
          <RatingBar ratings={code.ratings} />
          <div className="ca-chips" aria-label={t('dives.recentAttemptsFor', { code: code.dive_code })}>
            {code.recent.map(item => <ScoreChip key={item.id} id={item.id} performance={item.performance} score={item.score ?? 0} onOpen={onOpenClip}
              label={t('dives.openAttemptFrom', { code: code.dive_code, date: date(item.dive_datetime, 'd MMM HH:mm') })} />)}
            {code.attempt_count > code.recent.length && <span className="ca-flat" style={{ alignSelf: 'center', paddingLeft: 4, fontSize: 12 }}>+{code.attempt_count - code.recent.length}</span>}
          </div>
          <ChevronRight className="ca-code-go h-4 w-4" aria-hidden="true" />
        </div>
      })}
    </div>
  </div>
}
