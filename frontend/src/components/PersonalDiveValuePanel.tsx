import { ChevronDown, History } from 'lucide-react'
import { appLocale } from '../utils/dateLocale'
import { format, parseISO } from 'date-fns'
import { useEffect, useState } from 'react'
import i18n from '../i18n'
import {
  getPersonalDiveValue,
  getPersonalDiveValuePatterns,
  type HistoricalPattern,
  type PersonalDiveValue,
} from '../services/personalDiveValueApi'

/**
 * Personal Dive Value (PDV) panel copy, localized at render time; the API's
 * component keys (`technical`, `same_dive_relative`…) and confidence levels
 * stay canonical.
 */
const SIGNAL_KEYS: Record<string, string> = {
  technical: 'technical',
  same_dive_relative: 'sameDiveResult',
  breakthrough: 'breakthrough',
  progression: 'progression',
  consistency: 'consistency',
  novelty: 'novelty',
}

const signalLabel = (key: string) => {
  const suffix = SIGNAL_KEYS[key]
  return suffix ? i18n.t(`pdv.signals.${suffix}`) : key
}

function confidenceText(value: PersonalDiveValue['confidence']) {
  if (value.level === 'low') {
    return i18n.t('pdv.emergingConfidence', { count: value.same_dive_support })
  }
  if (value.level === 'undefined') return i18n.t('pdv.unavailable')
  return i18n.t('pdv.levelConfidence', {
    level: value.level[0].toUpperCase() + value.level.slice(1),
    count: value.same_dive_support,
  })
}

function PatternList({ matches, onOpenAttempt }: { matches: HistoricalPattern[]; onOpenAttempt?: (id: number) => void }) {
  if (!matches.length) return <p className="mt-3 text-xs leading-5 text-app-muted">{i18n.t('pdv.noPatterns')}</p>
  return <ol className="mt-3 space-y-2" aria-label={i18n.t('pdv.patternsAria')}>{matches.map((match, index) => <li key={match.attempt_id} className="border-l border-app-accent/60 bg-app-panel-elevated px-3 py-2 text-xs"><div className="flex flex-wrap items-center justify-between gap-2"><span className="font-medium text-app-text">{index === 0 ? i18n.t('pdv.closestPattern') : i18n.t('pdv.historicalMatch')}</span>{onOpenAttempt && <button type="button" onClick={() => onOpenAttempt(match.attempt_id)} className="min-h-0 border-0 bg-transparent p-0 text-xs text-app-accent">{i18n.t('analysis.openAttempt')}</button>}</div><p className="mt-1 text-app-muted">{format(parseISO(match.dive_datetime), 'd MMM yyyy', { locale: appLocale() })} · {match.height} · {match.is_sync ? 'SYNC' : i18n.t('analysis.individual')} · {match.modifiers.join(', ') || i18n.t('analysis.noModifiers')}</p><p className="mt-1 tabular-nums text-app-text">{i18n.t('pdv.earlier')} {match.trailing_scores.join(' · ')} <span className="text-app-muted">{i18n.t('pdv.vsCurrent')} {match.current_trailing_scores.join(' · ')}</span></p><p className="mt-1 text-app-muted">{match.evidence}</p></li>)}</ol>
}

export default function PersonalDiveValuePanel({ attemptId, onOpenAttempt }: { attemptId: number; onOpenAttempt?: (id: number) => void }) {
  const [value, setValue] = useState<PersonalDiveValue | null>(null)
  const [matches, setMatches] = useState<HistoricalPattern[]>([])
  const [state, setState] = useState<'loading' | 'ready' | 'disabled' | 'excluded' | 'error'>('loading')
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    setState('loading'); setValue(null); setMatches([]); setExpanded(false)
    Promise.all([getPersonalDiveValue(attemptId, controller.signal), getPersonalDiveValuePatterns(attemptId, controller.signal)])
      .then(([nextValue, patterns]) => { setValue(nextValue); setMatches(patterns.matches); setState('ready') })
      .catch((error: { status?: number; code?: string }) => {
        if (controller.signal.aborted) return
        if (error.status === 404 && error.code === 'personal_dive_value_disabled') setState('disabled')
        else if (error.status === 422 || error.status === 403) setState('excluded')
        else setState('error')
      })
    return () => controller.abort()
  }, [attemptId])

  if (state === 'disabled') return null
  if (state === 'loading') return <section className="mt-6 border border-app bg-app-panel-elevated p-4" role="status"><p className="text-sm text-app-muted">{i18n.t('common.loading')}</p></section>
  if (state === 'excluded') return <section className="mt-6 border border-app bg-app-panel-elevated p-4"><h3 className="font-semibold text-app-text">{i18n.t('pdv.titleUnavailable')}</h3><p className="mt-1 text-sm leading-6 text-app-muted">{i18n.t('pdv.excluded')}</p></section>
  if (state === 'error' || !value) return <section className="mt-6 border border-app bg-app-panel-elevated p-4"><h3 className="font-semibold text-app-text">{i18n.t('pdv.titleError')}</h3></section>
  if (value.value == null) return <section className="mt-6 border border-app bg-app-panel-elevated p-4"><h3 className="font-semibold text-app-text">{i18n.t('pdv.titleUnavailable')}</h3><p className="mt-1 text-sm leading-6 text-app-muted">{i18n.t('pdv.noOfficialDD')}</p><p className="mt-2 text-xs text-app-muted">{i18n.t('pdv.version', { version: value.version })} · {confidenceText(value.confidence)}</p></section>

  const ordered = Object.entries(value.components).sort(([, left], [, right]) => right.weighted_contribution - left.weighted_contribution)
  const summary = value.confidence.level === 'low'
    ? i18n.t('pdv.provisional')
    : `${value.components.same_dive_relative?.percentile != null ? i18n.t('pdv.sameDivePercentile', { percentile: value.components.same_dive_relative.percentile.toFixed(0) }) : ''}${i18n.t('pdv.strongestContribution', { signal: value.primary_signal || i18n.t('pdv.historicalContext') })}`
  return <section className="mt-6 overflow-hidden border border-app bg-app-panel" aria-labelledby="personal-value-heading"><div className="border-b border-app bg-[linear-gradient(110deg,rgba(84,190,171,.13),transparent_58%)] px-4 py-4"><div className="flex items-start justify-between gap-4"><div><h3 id="personal-value-heading" className="text-lg font-semibold text-app-text">{i18n.t('dashboard.personalDiveValue')}</h3></div><div className="text-right"><div className="text-3xl font-semibold tabular-nums text-app-text">{value.value}<span className="ml-1 text-sm font-normal text-app-muted">/ 100</span></div><div className="mt-1 text-xs text-app-muted">{i18n.t('pdv.executionLabel')} {value.execution.score.toFixed(1)} · DD {value.difficulty.official_dd?.toFixed(1)}</div></div></div><div className="mt-4 grid gap-2 text-sm sm:grid-cols-3"><div className="border-l border-app-accent px-3"><div className="text-xs text-app-muted">{i18n.t('pdv.primarySignal')}</div><div className="mt-1 font-medium text-app-text">{value.primary_signal || i18n.t('pdv.emerging')}</div></div><div className="border-l border-app px-3"><div className="text-xs text-app-muted">{i18n.t('pdv.confidence')}</div><div className="mt-1 font-medium text-app-text">{confidenceText(value.confidence)}</div></div><div className="border-l border-app px-3"><div className="text-xs text-app-muted">{i18n.t('pdv.signals.technical')}</div><div className="mt-1 font-medium text-app-text">{Math.round((value.components.technical?.normalized_value || 0) * 100)} / 100</div></div></div></div><div className="px-4 py-4"><p className="text-sm leading-6 text-app-muted">{summary}</p><button type="button" aria-expanded={expanded} onClick={() => setExpanded((current) => !current)} className="mt-4 flex w-full items-center justify-between gap-3 border border-app bg-app-panel-elevated px-3 py-2 text-xs font-medium text-app-text"><span>{expanded ? i18n.t('pdv.hideDetails') : i18n.t('pdv.showDetails')}</span><ChevronDown className={`h-4 w-4 transition-transform ${expanded ? 'rotate-180' : ''}`} /></button>{expanded && <div className="mt-4 space-y-5"><div><h4 className="text-sm font-semibold text-app-text">{i18n.t('pdv.whatContributed')}</h4><div className="mt-3 space-y-3">{ordered.map(([key, component]) => <div key={key}><div className="flex justify-between gap-3 text-xs"><span className="text-app-text">{signalLabel(key)}</span><span className="tabular-nums text-app-muted">{component.weighted_contribution.toFixed(1)} {i18n.t('analysis.points')} · {Math.round(component.weight * 100)}%</span></div><div className="mt-1 h-1.5 overflow-hidden bg-app-panel-elevated"><div className="h-full bg-app-accent" style={{ width: `${Math.max(2, component.normalized_value * 100)}%` }} /></div>{component.reason && <p className="mt-1 text-xs text-app-muted">{component.reason.replace(/_/g, ' ')}</p>}{key === 'same_dive_relative' && component.support != null && <p className="mt-1 text-xs text-app-muted">{i18n.t('pdv.basedOn', { count: component.support, percentile: component.percentile != null ? i18n.t('pdv.percentileSuffix', { percentile: component.percentile.toFixed(0) }) : '' })}</p>}</div>)}</div></div><div><div className="flex items-center gap-2"><History className="h-4 w-4 text-app-accent" /><h4 className="text-sm font-semibold text-app-text">{i18n.t('pdv.similarSequences')}</h4></div><PatternList matches={matches} onOpenAttempt={onOpenAttempt} /></div><div className="border-t border-app pt-3 text-xs text-app-muted"><p>{value.caveats.join(' ')}</p><p className="mt-1">{i18n.t('pdv.formula', { version: value.version, cutoff: format(parseISO(value.history_cutoff), 'd MMM yyyy, HH:mm', { locale: appLocale() }) })}</p></div></div>}</div></section>
}
