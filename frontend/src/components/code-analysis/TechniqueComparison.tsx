import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../services/api'

type Side = { label?: string; side: number; eligible: number; scored: number; sessions: number; recorded_matching: number; recorded_conflicting: number; inferred_only: number; mixed_unknown: number; median: number | null; q1: number | null; q3: number | null }
type Modifier = { modifiers: string; left_eligible: number; right_eligible: number; left_scored: number; right_scored: number }
export default function TechniqueComparison({ base, context, pair, revision, onTrack }: { onTrack: (id: number, name?: string) => void; base: string; context: object; pair: number[]; revision: number }) {
  const { t, i18n } = useTranslation()
  const [setAfter, setSetAfter] = useState(''), [setNext, setSetNext] = useState<string | null>(null)
  const [sets, setSets] = useState<Modifier[]>([]), [modifier, setModifier] = useState<string | null>(null)
  const [mode, setMode] = useState('periods'), [weighting, setWeighting] = useState('attempt')
  const [moreOthers, setMoreOthers] = useState(false)
  const [recordedEligible, setRecordedEligible] = useState<number | null>(null)
  const [otherTracks, setOtherTracks] = useState<{ id: number; track_id: number; name: string }[]>([])
  const [excluded, setExcluded] = useState<Record<string, number>>({}), [kind, setKind] = useState('periods')
  const [authError, setAuthError] = useState(false)
  const [inventoryLoading, setInventoryLoading] = useState(true), [resultLoading, setResultLoading] = useState(false), [resultReady, setResultReady] = useState(false), [retry, setRetry] = useState(0)
  const [labels, setLabels] = useState<(string | null)[]>([])
  const [sides, setSides] = useState<Side[]>([]), [error, setError] = useState('')
  const key = JSON.stringify({ context, pair, revision })
  useEffect(() => { setSetAfter('') }, [key])
  useEffect(() => {
    let current = true
    setAuthError(false); setInventoryLoading(true); setResultReady(false); setRecordedEligible(null); setExcluded({}); setOtherTracks([]); setLabels([]); setSides([]); setSets([]); setModifier(null); setError('')
    if (pair.length === 2) api.post(`${base}/modifier-sets`, { ...context, left: pair[0], right: pair[1], after: setAfter }).then(({ data }) => {
      if (current) { setInventoryLoading(false); setSetNext(data.next); setSets(data.items); if (!setAfter && !data.next && data.items.length === 1) setModifier(data.items[0].modifiers) }
    }).catch(error => { if (current) { setInventoryLoading(false); setAuthError(error?.response?.status === 401); setError(t(error?.response?.status === 401 ? 'technique.sessionExpired' : 'technique.comparisonUnavailable')) } })
    return () => { current = false }
  }, [base, key, setAfter, retry, t])
  useEffect(() => {
    let current = true
    setSides([]); setResultReady(false); setResultLoading(modifier !== null && pair.length === 2)
    if (modifier !== null && pair.length === 2) api.post(`${base}/compare`, { ...context, left: pair[0], right: pair[1], modifiers: modifier, mode, weighting }).then(({ data }) => { if (current) { setError(''); setResultLoading(false); setResultReady(true); setSides(data.sides); setLabels(data.labels ?? []); setRecordedEligible(data.recorded_eligible); setExcluded(data.excluded); setOtherTracks(data.other_tracks ?? []); setMoreOthers(Boolean(data.more_other_tracks)); setKind(data.kind) } }).catch(error => { if (current) { setResultLoading(false); setAuthError(error?.response?.status === 401); setError(t(error?.response?.status === 401 ? 'technique.sessionExpired' : 'technique.comparisonUnavailable')) } })
    return () => { current = false }
  }, [base, key, modifier, mode, weighting, retry, t])
  if (pair.length !== 2) return null
  if (error) return <div className="th-comparison"><p className="th-error" role="alert">{error}</p><>{authError && <a className="th-secondary" href="/login" target="_blank" rel="noreferrer">{t('technique.signInAgain')}</a>}<button className="th-secondary" onClick={() => setRetry(n => n + 1)}>{t('technique.retry')}</button></></div>
  const number = (value: number | null | undefined) => value == null ? '—' : new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1, minimumFractionDigits: 1 }).format(value)
  const comparable = sides.length === 2 && sides.every(s => s.scored > 0)
  return <div className="th-comparison">
<h3>{t('technique.ratingsDuring')}</h3><p className="th-setup-help">{t('technique.globalRatingLimit')}</p>
    <div className="th-compare-modes" role="group" aria-label={t('technique.compare')}><button aria-pressed={mode === 'periods'} onClick={() => setMode('periods')}>{t('technique.periods')}</button><button aria-pressed={mode === 'recorded'} onClick={() => setMode('recorded')}>{t('technique.recordedOnly')}{recordedEligible != null ? ` (${recordedEligible})` : ''}</button></div>
    {(sets.length > 1 || setAfter || setNext) && <label className="th-field">{t('technique.modifiers')}<select value={modifier ?? '__choose'} onChange={e => setModifier(e.target.value)}><option disabled value="__choose">{t('technique.chooseModifiers')}</option>{sets.map(s => <option key={s.modifiers} value={s.modifiers}>{s.modifiers || t('technique.noModifiers')} · {s.left_scored}/{s.left_eligible} | {s.right_scored}/{s.right_eligible}</option>)}</select></label>}
    <div className="th-pagination">{setAfter && <button onClick={() => setSetAfter('')}>{t('common.back')}</button>}{setNext && <button onClick={() => setSetAfter(setNext!)}>{t('technique.modifiers')}</button>}</div>
    {(inventoryLoading || resultLoading) && <p role="status" className="th-setup-help">{t('technique.loadingComparison')}</p>}
    {resultReady && <div className="th-coverage">{[0, 1].map(index => { const s = sides.find(s => s.side === index); return <section key={index}><h4>{s?.label ?? labels[index] ?? t(index ? 'technique.after' : 'technique.before')}</h4><p>{`${s?.scored ?? 0} / ${s?.eligible ?? 0} ${t('technique.scored')} · ${t('technique.sessionsCount', { count: s?.sessions ?? 0 })}`}</p>{s && <p>{mode === 'periods' ? t('technique.attributionBrief', { recorded: s.recorded_matching, conflicting: s.recorded_conflicting, inferred: s.inferred_only, unknown: s.mixed_unknown }) : t('technique.outsideIntended', { count: s.recorded_conflicting })}</p>}{mode === 'periods' && s && !s.recorded_matching && s.recorded_conflicting > 0 && <p>{t('technique.noMatchingUse')}</p>}{comparable && s?.scored === 1 ? <p className="th-single-score">{t('technique.singleRating', { score: number(s.median) })}</p> : comparable && <><strong className={`th-score${s && !s.recorded_matching && s.recorded_conflicting > 0 ? ' is-conflicted' : ''}`}>{number(s?.median)}</strong><span className="th-score-caption">{t('codeAnalysis.median')}</span></>}</section> })}</div>}
    {!inventoryLoading && !resultLoading && !resultReady && sets.length === 0 && <p className="th-no-comparison">{t('technique.noComparable')}</p>}
    {resultReady && !comparable && <p className="th-no-comparison">{t(modifier === null && sets.length > 1 ? 'technique.chooseModifiers' : 'technique.noComparable')}</p>}
    {resultReady && <details className="th-details"><summary>{t('technique.comparisonDetails')}</summary><div className="th-form">
      <label className="th-field">{t('technique.weighting')}<select value={weighting} onChange={e => setWeighting(e.target.value)}><option value="attempt">{t('technique.eachDive')}</option><option value="session">{t('technique.eachSession')}</option></select></label>
      <p>{t('technique.modifiers')}: {modifier || t('technique.noModifiers')}</p>
      {sides.map(s => <div key={s.side}><strong>{s.label}</strong><p>{t('technique.usualScores')}: {s.q1 != null && s.q3 != null ? `${number(s.q1)}–${number(s.q3)}` : '—'}</p><p>{t('technique.attribution', { matching: s.recorded_matching, conflicting: s.recorded_conflicting, inferred: s.inferred_only, unknown: s.mixed_unknown })}</p></div>)}
      {Object.values(excluded).some(n => n > 0) && <p>{t('technique.excluded')}: {Object.entries(excluded).filter(([, count]) => count > 0).map(([key, count]) => `${t(`technique.exclusion.${key}`)} ${count}`).join(' · ')}</p>}
      {kind === 'recorded-by-episode' && <p>{t('technique.recordedByEpisode')}</p>}
      {otherTracks.length > 0 && <div><p>{t('technique.otherChanges')}</p>{otherTracks.map(other => <button type="button" className="th-text-button" key={other.id} onClick={() => onTrack(other.track_id, other.name)}>{other.name}</button>)}</div>}
      {moreOthers && <p>{t('technique.moreTracks')}…</p>}
    </div></details>}
  </div>
}
