import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../services/api'

type Side = { label?: string; side: number; eligible: number; scored: number; sessions: number; recorded_matching: number; recorded_conflicting: number; inferred_only: number; mixed_unknown: number; median: number | null; q1: number | null; q3: number | null }
type Modifier = { modifiers: string; left_eligible: number; right_eligible: number; left_scored: number; right_scored: number }
export default function TechniqueComparison({ base, context, pair, revision, onTrack }: { onTrack: (id: number, name?: string) => void; base: string; context: object; pair: number[]; revision: number }) {
  const { t } = useTranslation()
  const [setAfter, setSetAfter] = useState(''), [setNext, setSetNext] = useState<string | null>(null)
  const [sets, setSets] = useState<Modifier[]>([]), [modifier, setModifier] = useState<string | null>(null)
  const [mode, setMode] = useState('periods'), [weighting, setWeighting] = useState('attempt')
  const [moreOthers, setMoreOthers] = useState(false)
  const [recordedEligible, setRecordedEligible] = useState<number | null>(null)
  const [otherTracks, setOtherTracks] = useState<{ id: number; track_id: number; name: string }[]>([])
  const [excluded, setExcluded] = useState<Record<string, number>>({}), [kind, setKind] = useState('periods')
  const [sides, setSides] = useState<Side[]>([]), [error, setError] = useState('')
  const key = JSON.stringify({ context, pair, revision })
  useEffect(() => { setSetAfter('') }, [key])
  useEffect(() => {
    let current = true
    setRecordedEligible(null); setExcluded({}); setOtherTracks([]); setSides([]); setSets([]); setModifier(null); setError('')
    if (pair.length === 2) api.post(`${base}/modifier-sets`, { ...context, left: pair[0], right: pair[1], after: setAfter }).then(({ data }) => {
      if (current) { setSetNext(data.next); setSets(data.items); if (!setAfter && !data.next && data.items.length === 1) setModifier(data.items[0].modifiers) }
    }).catch(error => { if (current) setError(t(error?.response?.status === 422 ? 'technique.noComparable' : 'technique.conflict')) })
    return () => { current = false }
  }, [base, key, setAfter, t])
  useEffect(() => {
    let current = true
    setSides([])
    if (modifier !== null && pair.length === 2) api.post(`${base}/compare`, { ...context, left: pair[0], right: pair[1], modifiers: modifier, mode, weighting }).then(({ data }) => { if (current) { setSides(data.sides); setRecordedEligible(data.recorded_eligible); setExcluded(data.excluded); setOtherTracks(data.other_tracks ?? []); setMoreOthers(Boolean(data.more_other_tracks)); setKind(data.kind) } }).catch(error => { if (current) setError(t(error?.response?.status === 422 ? 'technique.noComparable' : 'technique.conflict')) })
    return () => { current = false }
  }, [base, key, modifier, mode, weighting, t])
  if (pair.length !== 2) return null
  return <div><h3>{t('technique.ratingsDuring')}</h3>{error && <p role="alert">{error}</p>}
    <label>{t('technique.modifiers')} <select className="app-input" value={modifier ?? '__choose'} onChange={e => setModifier(e.target.value)}><option disabled value="__choose">—</option>{sets.map(s => <option key={s.modifiers} value={s.modifiers}>{s.modifiers || t('technique.noModifiers')} · {s.left_scored}/{s.left_eligible} | {s.right_scored}/{s.right_eligible}</option>)}</select></label>
    <button className="ca-btn" disabled={!setAfter} onClick={() => setSetAfter('')}>{t('common.back')}</button><button className="ca-btn" disabled={setNext === null} onClick={() => setSetAfter(setNext!)}>{t('technique.modifiers')}</button>
    <label>{t('technique.compare')} <select className="app-input" value={mode} onChange={e => setMode(e.target.value)}><option value="periods">{t('technique.periods')}</option><option value="recorded">{t('technique.recorded')}{recordedEligible != null ? ` (${recordedEligible})` : ''}</option></select></label>
    <label>{t('technique.weighting')} <select className="app-input" value={weighting} onChange={e => setWeighting(e.target.value)}><option value="attempt">{t('technique.attempt')}</option><option value="session">{t('technique.session')}</option></select></label>
    <div>{otherTracks.map(other => <button type="button" className="ca-btn" key={other.id} onClick={() => onTrack(other.track_id, other.name)}>{other.name} · #{other.id}</button>)}</div>
    {moreOthers && <p>{t('technique.moreTracks')}…</p>}
    <p>{t('technique.excluded')}: {Object.entries(excluded).map(([key, count]) => `${t(`technique.exclusion.${key}`)} ${count}`).join(' · ')}</p>
    {kind === 'recorded-by-episode' && <p>{t('technique.recordedByEpisode')}</p>}
    <div>{[0, 1].map(index => { const s = sides.find(s => s.side === index); return <section key={index}><h4>{s?.label} · #{pair[index]}</h4><p>{t('technique.coverage', { scored: s?.scored ?? 0, eligible: s?.eligible ?? 0, sessions: s?.sessions ?? 0 })}</p>{s && <p>{mode === 'periods' ? t('technique.attribution', { matching: s.recorded_matching, conflicting: s.recorded_conflicting, inferred: s.inferred_only, unknown: s.mixed_unknown }) : t('technique.outsideIntended', { count: s.recorded_conflicting })}</p>}</section> })}</div>
    {sides.length === 2 && sides.every(s => s.scored > 0) ? <table><thead><tr><th>{t('technique.label')}</th><th>{t('codeAnalysis.median')}</th><th>IQR</th></tr></thead><tbody>{sides.map(s => <tr key={s.side}><th>{s.label} · #{pair[s.side]}</th><td>{s.median ?? '—'}</td><td>{s.q1 != null && s.q3 != null ? `${s.q1}–${s.q3}` : '—'}</td></tr>)}</tbody></table> : <p>{t('technique.noComparable')}</p>}

  </div>
}
