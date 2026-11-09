import DiveThumbnail from '../DiveThumbnail'
import TechniqueTrackChart from './TechniqueTrackChart'
import TechniqueComparison from './TechniqueComparison'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../services/api'

type Track = { id: number; name: string; revision: number }
type Episode = { position?: string | null; sync?: boolean | null; anchor_unavailable?: boolean; id: number; label: string | null; start_at: string; end_at: string | null; uncertain_until: string | null; scope: string; gap: boolean; technique_id: number | null }
type Attempt = { recorded_episode_deleted?: boolean; recorded_episode_id?: number; late_import?: boolean; use_label?: string; video_uuid?: string; dive_code: string; id: number; dive_datetime: string; history_occurred_at: string; state: string; source: string; episode_id: number | null }
type Context = { code: string; apparatus: string; height: string; position: string; sync: boolean }

export default function TechniqueHistory({ diver, context, onSelected }: { diver: number; context: Context; onSelected?: (active: boolean) => void }) {
  const { t } = useTranslation()
  const [trackAfter, setTrackAfter] = useState(0)
  const [chartActive, setChartActive] = useState(false)
  const [trackNext, setTrackNext] = useState<number | null>(null)
  const [tracks, setTracks] = useState<Track[]>([]), [track, setTrack] = useState<number | null>(null)
  const [revision, setRevision] = useState(0), [episodes, setEpisodes] = useState<Episode[]>([])
  const [attempts, setAttempts] = useState<Attempt[]>([]), [after, setAfter] = useState(0), [next, setNext] = useState<number | null>(null)
  const [selected, setSelected] = useState<number[]>([]), [pair, setPair] = useState<number[]>([])
  const [label, setLabel] = useState(''), [anchor, setAnchor] = useState<number | null>(null), [family, setFamily] = useState(false)
  const [sessionFilter, setSessionFilter] = useState(''), [fromFilter, setFromFilter] = useState(''), [toFilter, setToFilter] = useState('')
  const [endDate, setEndDate] = useState('')
  const [timezone, setTimezone] = useState('UTC'), [notes, setNotes] = useState(''), [narrowPosition, setNarrowPosition] = useState(false), [narrowSync, setNarrowSync] = useState(false)
  const [copyHeight, setCopyHeight] = useState(context.height), [copyApparatus, setCopyApparatus] = useState(context.apparatus), [copyDetails, setCopyDetails] = useState<{ scope: { scope: string }; upcoming: { start_at: string } | null; counts?: { affected: number; explicit_preserved: number } }[]>([])
  const [planSummary, setPlanSummary] = useState<{ upcoming?: { start_at: string }; counts?: { affected: number; explicit_preserved: number } } | null>(null)
  const [copyScopes, setCopyScopes] = useState(''), [copyPreview, setCopyPreview] = useState<{ revision: number; episode_id: number; targets: { scope: string; apparatus: string; height: string }[] } | null>(null)
  const [episodeAfter, setEpisodeAfter] = useState(0), [episodeNext, setEpisodeNext] = useState<number | null>(null), [trackName, setTrackName] = useState('')
  const [dateStart, setDateStart] = useState(''), [uncertainUntil, setUncertainUntil] = useState(''), [gap, setGap] = useState(false), [identity, setIdentity] = useState<number | null>(null), [edit, setEdit] = useState<number | null>(null)
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null), [error, setError] = useState('')
  const [reload, setReload] = useState(0), [busy, setBusy] = useState(false)
  const generation = useRef(0)
  const contextKey = JSON.stringify(context)
  useEffect(() => { onSelected?.(pair.length > 0 || chartActive); return () => onSelected?.(false) }, [pair.length, chartActive, onSelected])
  const base = `/technique-history/${diver}`
  useEffect(() => {
    const g = ++generation.current
    setLabel(''); setIdentity(null); setEdit(null); setDateStart(''); setUncertainUntil(''); setAnchor(null); setCopyPreview(null); setBusy(false); setPair([]); setAfter(0); setEpisodeAfter(0); setTrackAfter(0); setTracks([]); setTrack(null); setEpisodes([]); setAttempts([]); setSelected([]); setPreview(null); setError('')
    api.get('/technique-history/preferences').then(({ data }) => { if (g === generation.current) setTimezone(data.timezone) }).catch(() => {})
    api.get(`${base}/tracks`).then(({ data }) => { if (g === generation.current) { setTrackNext(data.next); setTracks(data.items); setTrack(data.items[0]?.id ?? null) } }).catch(() => { if (g === generation.current) setError(t('technique.unavailable')) })
    return () => { generation.current++ }
  }, [base, contextKey, t])
  useEffect(() => {
    if (!track) return
    const g = ++generation.current
    setCopyPreview(null); setPreview(null); setSelected([]); setError('')
    Promise.all([api.get(`${base}/${track}/episodes?after=${episodeAfter}`), api.post(`${base}/${track}/attempts`, { ...context, after, session_id: sessionFilter ? Number(sessionFilter) : null, from_date: fromFilter || null, to_date: toFilter || null })]).then(([e, a]) => {
      if (g !== generation.current) return
      if (e.data.revision !== a.data.revision) { setError(t('technique.conflict')); return }
      setEpisodeNext(e.data.next); setEpisodes(e.data.items); setRevision(e.data.revision); setAttempts(a.data.items); setNext(a.data.next)
    }).catch(() => { if (g === generation.current) setError(t('technique.unavailable')) })
    return () => { generation.current++ }
  }, [base, track, contextKey, after, episodeAfter, sessionFilter, fromFilter, toFilter, reload, t])
  async function mutate(path: string, body: unknown) {
    const g = generation.current
    setBusy(true); setError('')
    try {
      const { data } = await api.post(`${base}/${track}/${path}`, body)
      if (g !== generation.current) return
      if (path === 'preview') { setPreview(data.change); setPlanSummary(data) }
      else { setPreview(null); setEdit(null); setLabel(''); setIdentity(null); setReload(v => v + 1) }
    } catch { if (g === generation.current) setError(t('technique.conflict')) }
    finally { if (g === generation.current) setBusy(false) }
  }
  const familyCode = context.code.startsWith('5') ? context.code.slice(0, 2) : context.code.slice(0, 1)
  const canFamily = ['1','2','3','4','51','52','53','54'].includes(familyCode)
  return <section className="ca-panel" aria-label={t('technique.title')}>
    <div className="ca-panel-h"><h2>{t('technique.title')}</h2></div>
    {error && <p role="alert">{error}</p>}
    {!tracks.length && <button className="ca-btn" disabled={busy} onClick={async () => {
      const g = generation.current
      setBusy(true)
      try { const { data } = await api.post(`${base}/tracks`, { name: 'General' }); if (g === generation.current) { setTracks([data]); setTrack(data.id) } }
      catch { if (g === generation.current) setError(t('technique.conflict')) }
      finally { if (g === generation.current) setBusy(false) }
    }}>{t('technique.enable')}</button>}
    {!!tracks.length && <>
      <form onSubmit={async e => { e.preventDefault(); const g = generation.current; try { const { data } = await api.post(`${base}/tracks`, { name: trackName }); if (g === generation.current) { setTracks(p => [...p, data]); setTrack(data.id); setTrackName('') } } catch { if (g === generation.current) setError(t('technique.conflict')) } }}><label>{t('technique.track')} <input className="app-input" required maxLength={80} value={trackName} onChange={e => setTrackName(e.target.value)} /></label><button className="ca-btn">+</button></form>
      <label>{t('technique.track')} <select className="app-input" value={track ?? ''} onChange={e => { setTrack(Number(e.target.value)); setPair([]); setAfter(0); setEpisodeAfter(0); setBusy(false) }}>{tracks.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
      <button className="ca-btn" disabled={!trackAfter} onClick={async () => { const g = generation.current; try { const { data } = await api.get(`${base}/tracks`); if (g === generation.current) { setTrackAfter(0); setTracks(data.items); setTrackNext(data.next); setTrack(data.items[0]?.id ?? null); setPair([]) } } catch { if (g === generation.current) setError(t('technique.conflict')) } }}>{t('common.back')}</button>
      <button className="ca-btn" disabled={trackNext === null} onClick={async () => { const g = generation.current; try { const { data } = await api.get(`${base}/tracks?after=${trackNext}`); if (g === generation.current) { setTrackAfter(trackNext!); setTracks(data.items); setTrackNext(data.next); setTrack(data.items[0]?.id ?? null); setPair([]); setEpisodeAfter(0); setAfter(0) } } catch { if (g === generation.current) setError(t('technique.conflict')) } }}>{t('technique.moreTracks')}</button>
      <p>{context.code} · {context.apparatus} · {context.height} · {context.position}{context.sync ? ' · SYNC' : ''}</p>
      <form onSubmit={e => { e.preventDefault(); const a = attempts.find(a => a.id === anchor); if (a || dateStart) void mutate('preview', { ...context, revision, label, notes, timezone, constrain_position: narrowPosition, constrain_sync: narrowSync, technique_id: identity, episode_id: edit, gap, scope: family ? familyCode : context.code, start_at: a?.history_occurred_at ?? dateStart, anchor_id: a?.id, uncertain_until: uncertainUntil || null, precision: uncertainUntil ? 'approximate' : a ? 'attempt' : 'date' }) }}>
        <label>{t('technique.label')} <input className="app-input" maxLength={120} required={!gap && identity === null} value={label} onChange={e => { setLabel(e.target.value); setPreview(null) }} /></label>
        <label>{t('technique.start')} <select className="app-input" required={!dateStart} value={anchor ?? ''} onChange={e => { setAnchor(e.target.value ? Number(e.target.value) : null); setPreview(null) }}><option value="">—</option>{attempts.map(a => <option key={a.id} value={a.id}>{a.dive_datetime} · #{a.id}</option>)}</select></label>
        <details><summary>{t('technique.options')}</summary>
        <label>{t('technique.date')} <input className="app-input" type="datetime-local" value={dateStart} onChange={e => { setDateStart(e.target.value); setAnchor(null); setPreview(null) }} /></label>
        <label>{t('technique.approximate')} <input className="app-input" type="datetime-local" value={uncertainUntil} onChange={e => { setUncertainUntil(e.target.value); setPreview(null) }} /></label>
        <label><input type="checkbox" checked={gap} onChange={e => { setGap(e.target.checked); setPreview(null) }} />{t('technique.unknown')}</label>
        <label>{t('technique.reuse')} <select className="app-input" value={identity ?? ''} onChange={e => { setIdentity(e.target.value ? Number(e.target.value) : null); setPreview(null) }}><option value="">—</option>{episodes.filter((e, i, all) => e.technique_id && all.findIndex(other => other.technique_id === e.technique_id) === i).map(e => <option key={e.technique_id} value={e.technique_id!}>{e.label}</option>)}</select></label>
        {canFamily && <label><input type="checkbox" checked={family} onChange={e => { setFamily(e.target.checked); setPreview(null) }} />{t('technique.family', { family: familyCode })}</label>}
        <label>{t('technique.timezone')} <input className="app-input" maxLength={80} value={timezone} onChange={e => { setTimezone(e.target.value); setPreview(null) }} onBlur={() => { const g = generation.current; void api.post('/technique-history/preferences', { timezone }).catch(() => { if (g === generation.current) setError(t('technique.conflict')) }) }} /></label>
        <label>{t('technique.notes')} <textarea className="app-input" maxLength={2000} value={notes} onChange={e => { setNotes(e.target.value); setPreview(null) }} /></label>
        <label><input type="checkbox" checked={narrowPosition} onChange={e => { setNarrowPosition(e.target.checked); setPreview(null) }} />{context.position}</label><label><input type="checkbox" checked={narrowSync} onChange={e => { setNarrowSync(e.target.checked); setPreview(null) }} />SYNC {String(context.sync)}</label>
        </details>
        <button className="ca-btn" disabled={busy}>{t('technique.preview')}</button>
      </form>
      {preview && <div role="region" aria-label={t('technique.preview')}><p>{String(preview.scope)} · {String(preview.start_at)}</p><p>{t('technique.previewCounts', { affected: planSummary?.counts?.affected ?? 0, explicit: planSummary?.counts?.explicit_preserved ?? 0 })}{planSummary?.upcoming ? ` · ${planSummary.upcoming.start_at}` : ''}</p><button className="ca-btn" disabled={busy} onClick={() => void mutate('changes', preview)}>{t('common.save')}</button></div>}
      <ol>{episodes.map(e => <li key={e.id}><button type="button" className="ca-btn" aria-pressed={pair.includes(e.id)} onClick={() => setPair(p => p.includes(e.id) ? p.filter(id => id !== e.id) : [...p.slice(-1), e.id])}>{e.label ?? t('technique.unknown')} · {e.start_at}{e.end_at ? ` → ${e.end_at}` : ''}{e.uncertain_until ? ` ≈ ${e.uncertain_until}` : ''} · {e.scope}{e.anchor_unavailable ? ` · ${t('technique.anchorUnavailable')}` : ''}</button><button className="ca-btn" onClick={() => { setNarrowPosition(e.position != null); setNarrowSync(e.sync != null); setTimezone('UTC'); setEdit(e.id); setDateStart(e.start_at.slice(0,16)); setAnchor(null); setLabel(e.label ?? ''); setIdentity(e.technique_id); setGap(e.gap); setPreview(null) }}>{t('technique.edit')}</button><button className="ca-btn" disabled={busy} onClick={async () => { const g = generation.current; try { const { data } = await api.post(`${base}/${track}/episodes/${e.id}/delete`, { revision }); if (g === generation.current && window.confirm(`${t('technique.deletePreview')} (${data.preview.eligible}; ${data.preview.explicit_preserved})`)) void mutate(`episodes/${e.id}/delete`, { revision, commit: true }) } catch { if (g === generation.current) setError(t('technique.conflict')) } }}>{t('technique.delete')}</button></li>)}</ol>
      <button className="ca-btn" disabled={!episodeAfter} onClick={() => setEpisodeAfter(0)}>{t('common.back')}</button><button className="ca-btn" disabled={episodeNext === null} onClick={() => setEpisodeAfter(episodeNext!)}>{t('technique.nextPeriods')}</button>
      <details><summary>{t('technique.filters')}</summary><label>{t('technique.session')} <input className="app-input" type="number" min="1" value={sessionFilter} onChange={e => { setSessionFilter(e.target.value); setAfter(0) }} /></label><label>{t('technique.fromUtc')} <input className="app-input" type="datetime-local" value={fromFilter} onChange={e => { setFromFilter(e.target.value); setAfter(0) }} /></label><label>{t('technique.toUtc')} <input className="app-input" type="datetime-local" value={toFilter} onChange={e => { setToFilter(e.target.value); setAfter(0) }} /></label></details>
      <button className="ca-btn" onClick={() => setSelected(attempts.map(a => a.id))}>{t('technique.selectPage')}</button><button className="ca-btn" disabled={selected.length < 2} onClick={() => { const indices = selected.map(id => attempts.findIndex(a => a.id === id)).filter(i => i >= 0); setSelected(attempts.slice(Math.min(...indices), Math.max(...indices) + 1).map(a => a.id)) }}>{t('technique.selectRange')}</button>
      <fieldset><legend>{t('technique.recorded')}</legend>{attempts.map(a => <label key={a.id} style={{ display: 'block', padding: 8, borderLeft: pair.includes(a.episode_id ?? -1) ? '3px solid currentColor' : undefined }}><input type="checkbox" checked={selected.includes(a.id)} onChange={e => setSelected(p => e.target.checked ? [...p, a.id] : p.filter(id => id !== a.id))} /> <span className="ca-thumb" style={{ display: 'inline-block', width: 64 }}><DiveThumbnail dive={a} compact /></span> {a.dive_datetime}{a.dive_datetime !== a.history_occurred_at ? ` · ${t('technique.historyOrder')}: ${a.history_occurred_at}` : ''} · {t(`technique.${a.source}`)} · {t(`technique.${a.state}`)} {a.use_label}{a.recorded_episode_deleted ? ` · ${t('technique.deletedPeriod')} #${a.recorded_episode_id}` : ''}{a.late_import ? ` · ${t('technique.lateImport')}` : ''}</label>)}</fieldset>
      <button className="ca-btn" disabled={!after} onClick={() => setAfter(0)}>{t('common.back')}</button>
      <button className="ca-btn" disabled={next == null} onClick={() => setAfter(next!)}>{t('technique.next')}</button>
      {[...new Set(attempts.map(a => (a as Attempt & { session_id: number }).session_id))].filter(Boolean).map(session => <div key={session}>{t('technique.session')} #{session} {(['mixed', 'unknown'] as const).map(state => <button className="ca-btn" key={state} disabled={busy} onClick={() => void mutate('session-state', { ...context, revision, session_id: session, state })}>{t(`technique.${state}`)}</button>)}</div>)}
      <select className="app-input" aria-label={t('technique.recorded')} value="" disabled={!selected.length || busy} onChange={e => { if (e.target.value) void mutate('assign', { ...context, revision, ids: selected, state: 'technique', technique_id: Number(e.target.value) }) }}><option value="">{t('technique.recorded')}</option>{episodes.filter(e => e.technique_id).map(e => <option key={e.id} value={e.technique_id!}>{e.label}</option>)}</select>
      {(['mixed', 'unknown'] as const).map(state => <button key={state} className="ca-btn" disabled={!selected.length || busy} onClick={() => void mutate('assign', { ...context, revision, ids: selected, state })}>{t(`technique.${state}`)}</button>)}
      {selected.length === 1 && endDate && <button className="ca-btn" disabled={busy} onClick={async () => { const g = generation.current; const body = { revision, attempt_id: selected[0], occurred_at: endDate }; try { const { data } = await api.post(`${base}/${track}/correct-order`, body); if (g === generation.current && window.confirm(`${t('technique.correctOrder')} · ${data.preview.affected_attempts}`)) void mutate('correct-order', { ...body, track_revisions: data.preview.track_revisions, commit: true }) } catch { if (g === generation.current) setError(t('technique.conflict')) } }}>{t('technique.correctOrder')}</button>}
      {pair.length === 1 && <details><summary>{t('technique.edit')}</summary><label>{t('technique.endUtc')} <input className="app-input" type="datetime-local" value={endDate} onChange={e => setEndDate(e.target.value)} /></label><button className="ca-btn" disabled={!endDate || busy} onClick={async () => { const g = generation.current; const body = { revision, episode_id: pair[0], end_at: endDate }; try { await api.post(`${base}/${track}/end`, body); if (g === generation.current && window.confirm(t('technique.deletePreview'))) void mutate('end', { ...body, commit: true }) } catch { if (g === generation.current) setError(t('technique.conflict')) } }}>{t('technique.end')}</button><button className="ca-btn" disabled={!label || busy} onClick={() => { const e = episodes.find(e => e.id === pair[0]); if (e?.technique_id) void mutate(`techniques/${e.technique_id}/rename`, { revision, label }) }}>{t('technique.rename')}</button></details>}
      {pair.length === 1 && <form onSubmit={async e => { e.preventDefault(); const body = { revision, episode_id: pair[0], targets: copyScopes.split(',').map(scope => ({ scope: scope.trim(), apparatus: copyApparatus, height: copyHeight })) }; const g = generation.current; try { const { data } = await api.post(`${base}/${track}/copy`, body); if (g === generation.current) { setCopyPreview(body); setCopyDetails(data.targets) } } catch { if (g === generation.current) setError(t('technique.conflict')) } }}><label>{t('technique.alsoApply')} <input className="app-input" required maxLength={175} value={copyScopes} onChange={e => { setCopyScopes(e.target.value); setCopyPreview(null) }} /></label><label>{t('technique.apparatus')} <input className="app-input" required maxLength={20} value={copyApparatus} onChange={e => { setCopyApparatus(e.target.value); setCopyPreview(null) }} /></label><label>{t('attemptDetail.height')} <input className="app-input" required maxLength={5} value={copyHeight} onChange={e => { setCopyHeight(e.target.value); setCopyPreview(null) }} /></label><button className="ca-btn">{t('technique.preview')}</button></form>}
      {copyPreview && <div><ul>{copyDetails.map(d => <li key={d.scope.scope}>{d.scope.scope} · {d.upcoming?.start_at ?? '—'} · {t('technique.previewCounts', { affected: d.counts?.affected ?? 0, explicit: d.counts?.explicit_preserved ?? 0 })}</li>)}</ul><p>{copyPreview.targets.map(target => `${target.scope} · ${target.apparatus} · ${target.height}`).join('; ')}</p><button className="ca-btn" disabled={busy} onClick={() => { void mutate('copy', { ...copyPreview, commit: true }); setCopyPreview(null) }}>{t('common.save')}</button></div>}
      <button className="ca-btn" aria-pressed={chartActive} onClick={() => { setChartActive(v => !v); setPair([]) }}>{t('technique.title')}</button>
      {(chartActive || pair.length === 1) && pair.length < 2 && <TechniqueTrackChart base={`${base}/${track}`} context={context} revision={revision} selected={pair[0]} onSelect={id => setPair([id])} />}
      <TechniqueComparison onTrack={(id, name) => { setTracks(p => p.some(t => t.id === id) ? p : [...p, { id, name: name ?? `#${id}`, revision: 0 }]); setTrack(id); setPair([]); setAfter(0); setEpisodeAfter(0) }} base={`${base}/${track}`} context={context} pair={pair} revision={revision} />
      <button className="ca-btn" disabled={busy} onClick={() => void mutate('undo', { revision })}>{t('technique.undo')}</button>
    </>}
  </section>
}
