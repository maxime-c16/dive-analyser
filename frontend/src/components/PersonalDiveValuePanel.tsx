import { ChevronDown, History } from 'lucide-react'
import { appLocale } from '../utils/dateLocale'
import { format, parseISO } from 'date-fns'
import { useEffect, useState } from 'react'
import {
  getPersonalDiveValue,
  getPersonalDiveValuePatterns,
  type HistoricalPattern,
  type PersonalDiveValue,
} from '../services/personalDiveValueApi'

const LABELS: Record<string, string> = {
  technical: 'Technical magnitude', same_dive_relative: 'Same-dive result', breakthrough: 'Breakthrough',
  progression: 'Progression', consistency: 'Consistency', novelty: 'Novelty',
}

function confidenceText(value: PersonalDiveValue['confidence']) {
  if (value.level === 'low') return `Emerging · ${value.same_dive_support} prior same-dive attempts`
  if (value.level === 'undefined') return 'Unavailable'
  return `${value.level[0].toUpperCase()}${value.level.slice(1)} confidence · ${value.same_dive_support} prior attempts`
}

function PatternList({ matches, onOpenAttempt }: { matches: HistoricalPattern[]; onOpenAttempt?: (id: number) => void }) {
  if (!matches.length) return <p className="mt-3 text-xs leading-5 text-app-muted">No earlier same-dive sequence to compare.</p>
  return <ol className="mt-3 space-y-2" aria-label="Historical pattern matches">{matches.map((match, index) => <li key={match.attempt_id} className="border-l border-app-accent/60 bg-app-panel-elevated px-3 py-2 text-xs"><div className="flex flex-wrap items-center justify-between gap-2"><span className="font-medium text-app-text">{index === 0 ? 'Closest previous pattern' : 'Historical match'}</span>{onOpenAttempt && <button type="button" onClick={() => onOpenAttempt(match.attempt_id)} className="min-h-0 border-0 bg-transparent p-0 text-xs text-app-accent">Open attempt</button>}</div><p className="mt-1 text-app-muted">{format(parseISO(match.dive_datetime), 'd MMM yyyy', { locale: appLocale() })} · {match.height} · {match.is_sync ? 'SYNC' : 'Individual'} · {match.modifiers.join(', ') || 'No modifiers'}</p><p className="mt-1 tabular-nums text-app-text">Earlier {match.trailing_scores.join(' · ')} <span className="text-app-muted">vs current {match.current_trailing_scores.join(' · ')}</span></p><p className="mt-1 text-app-muted">{match.evidence}</p></li>)}</ol>
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
  if (state === 'loading') return <section className="mt-6 border border-app bg-app-panel-elevated p-4" role="status"><p className="text-sm text-app-muted">Loading…</p></section>
  if (state === 'excluded') return <section className="mt-6 border border-app bg-app-panel-elevated p-4"><h3 className="font-semibold text-app-text">Personal Dive Value unavailable</h3><p className="mt-1 text-sm leading-6 text-app-muted">Excluded for this attempt (e.g. straight jump or lineup).</p></section>
  if (state === 'error' || !value) return <section className="mt-6 border border-app bg-app-panel-elevated p-4"><h3 className="font-semibold text-app-text">Personal Dive Value could not be loaded</h3></section>
  if (value.value == null) return <section className="mt-6 border border-app bg-app-panel-elevated p-4"><h3 className="font-semibold text-app-text">Personal Dive Value unavailable</h3><p className="mt-1 text-sm leading-6 text-app-muted">Official DD is not defined for this attempt.</p><p className="mt-2 text-xs text-app-muted">Version {value.version} · {confidenceText(value.confidence)}</p></section>

  const ordered = Object.entries(value.components).sort(([, left], [, right]) => right.weighted_contribution - left.weighted_contribution)
  return <section className="mt-6 overflow-hidden border border-app bg-app-panel" aria-labelledby="personal-value-heading"><div className="border-b border-app bg-[linear-gradient(110deg,rgba(84,190,171,.13),transparent_58%)] px-4 py-4"><div className="flex items-start justify-between gap-4"><div><h3 id="personal-value-heading" className="text-lg font-semibold text-app-text">Personal Dive Value</h3></div><div className="text-right"><div className="text-3xl font-semibold tabular-nums text-app-text">{value.value}<span className="ml-1 text-sm font-normal text-app-muted">/ 100</span></div><div className="mt-1 text-xs text-app-muted">Execution {value.execution.score.toFixed(1)} · DD {value.difficulty.official_dd?.toFixed(1)}</div></div></div><div className="mt-4 grid gap-2 text-sm sm:grid-cols-3"><div className="border-l border-app-accent px-3"><div className="text-xs text-app-muted">Primary signal</div><div className="mt-1 font-medium text-app-text">{value.primary_signal || 'Emerging'}</div></div><div className="border-l border-app px-3"><div className="text-xs text-app-muted">Confidence</div><div className="mt-1 font-medium text-app-text">{confidenceText(value.confidence)}</div></div><div className="border-l border-app px-3"><div className="text-xs text-app-muted">Technical magnitude</div><div className="mt-1 font-medium text-app-text">{Math.round((value.components.technical?.normalized_value || 0) * 100)} / 100</div></div></div></div><div className="px-4 py-4"><p className="text-sm leading-6 text-app-muted">{value.confidence.level === 'low' ? 'Provisional: not enough same-dive history.' : `${value.components.same_dive_relative?.percentile != null ? `${value.components.same_dive_relative.percentile.toFixed(0)}th same-dive percentile. ` : ''}${value.primary_signal || 'Historical context'} is the strongest contribution.`}</p><button type="button" aria-expanded={expanded} onClick={() => setExpanded((current) => !current)} className="mt-4 flex w-full items-center justify-between border border-app bg-app-panel-elevated px-3 py-2 text-left text-sm text-app-text"><span>{expanded ? 'Hide details' : 'Show details'}</span><ChevronDown className={`h-4 w-4 transition-transform ${expanded ? 'rotate-180' : ''}`} /></button>{expanded && <div className="mt-4 space-y-5"><div><h4 className="text-sm font-semibold text-app-text">What contributed</h4><div className="mt-3 space-y-3">{ordered.map(([key, component]) => <div key={key}><div className="flex justify-between gap-3 text-xs"><span className="text-app-text">{LABELS[key] || key}</span><span className="tabular-nums text-app-muted">{component.weighted_contribution.toFixed(1)} points · {Math.round(component.weight * 100)}%</span></div><div className="mt-1 h-1.5 overflow-hidden bg-app-panel-elevated"><div className="h-full bg-app-accent" style={{ width: `${Math.max(2, component.normalized_value * 100)}%` }} /></div>{component.reason && <p className="mt-1 text-xs text-app-muted">{component.reason.replace(/_/g, ' ')}</p>}{key === 'same_dive_relative' && component.support != null && <p className="mt-1 text-xs text-app-muted">Based on {component.support} earlier same-dive attempts{component.percentile != null ? ` · ${component.percentile.toFixed(0)}th percentile` : ''}.</p>}</div>)}</div></div><div><div className="flex items-center gap-2"><History className="h-4 w-4 text-app-accent" /><h4 className="text-sm font-semibold text-app-text">Similar prior sequences</h4></div><PatternList matches={matches} onOpenAttempt={onOpenAttempt} /></div><div className="border-t border-app pt-3 text-xs text-app-muted"><p>{value.caveats.join(' ')}</p><p className="mt-1">Formula {value.version} · calculated from attempts before {format(parseISO(value.history_cutoff), 'd MMM yyyy, HH:mm', { locale: appLocale() })}.</p></div></div>}</div></section>
}
