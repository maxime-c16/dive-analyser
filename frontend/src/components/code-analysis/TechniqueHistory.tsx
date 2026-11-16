import { techniqueImpact } from './techniqueText'
import './techniqueHistory.css'
import { createPortal } from 'react-dom'
import TechniqueSetup, { type SetupEpisode } from './TechniqueSetup'
import TechniqueDialog from './TechniqueDialog'
import { techniqueDate, techniqueDateTime, techniqueInputDate } from './techniqueDates'
import { Plus, SlidersHorizontal, ArrowLeftRight, ChevronRight, Check, Pencil, Share2, ListChecks } from 'lucide-react'
import DiveThumbnail from '../DiveThumbnail'
import TechniqueTrackChart from './TechniqueTrackChart'
import TechniqueComparison from './TechniqueComparison'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../services/api'

type Track = { id: number; name: string; revision: number }
type Episode = { anchor_id?: number | null; notes?: string; apparatus?: string; height?: string; position?: string | null; sync?: boolean | null; anchor_unavailable?: boolean; id: number; label: string | null; start_at: string; end_at: string | null; uncertain_until: string | null; scope: string; gap: boolean; technique_id: number | null }
type Attempt = { session_index?: number; session_total?: number; session_id?: number; recorded_episode_deleted?: boolean; recorded_episode_id?: number; late_import?: boolean; use_label?: string; video_uuid?: string; dive_code: string; id: number; dive_datetime: string; history_occurred_at: string; state: string; source: string; episode_id: number | null }
type Context = { code: string; apparatus: string; height: string; position: string; sync: boolean }

export default function TechniqueHistory({ diver, context, viewer }: { viewer?: string|number; diver: number; context: Context }) {
  const { t } = useTranslation()
  const [trackAfter, setTrackAfter] = useState(0)
  const [chartActive, setChartActive] = useState(true)
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
  const [otherCode, setOtherCode] = useState('')
  const [copyScopes, setCopyScopes] = useState(''), [copyPreview, setCopyPreview] = useState<{ revision: number; episode_id: number; targets: { scope: string; apparatus: string; height: string }[] } | null>(null)
  const [episodeAfter, setEpisodeAfter] = useState(0), [episodeNext, setEpisodeNext] = useState<number | null>(null), [trackName, setTrackName] = useState('')
  const [dateStart, setDateStart] = useState(''), [uncertainUntil, setUncertainUntil] = useState(''), [gap, setGap] = useState(false), [identity, setIdentity] = useState<number | null>(null), [edit, setEdit] = useState<number | null>(null)
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null), [error, setError] = useState('')
  const [reload, setReload] = useState(0), [busy, setBusy] = useState(false)
  const [panel, setPanel] = useState<'change' | 'manage' | 'log' | 'share' | null>(null)
  const [comparing, setComparing] = useState(false)
  const [notice, setNotice] = useState('')
  const [hasDraft,setHasDraft]=useState(false)
  const [setupReady,setSetupReady]=useState(false)
  const [setup, setSetup] = useState(false)
  const [setupEpisode, setSetupEpisode] = useState<SetupEpisode | undefined>()
  const { i18n } = useTranslation()
  const date = (value: string) => techniqueDate(value, i18n.language)
  const periodDate = (value: string, other: string | null) => other?.slice(0,10) === value.slice(0,10) ? techniqueDateTime(value, i18n.language) : date(value)
  const scopeLabel = (scope: string) => ['1','2','3','4','51','52','53','54'].includes(scope) ? t(`technique.family${scope}`) : scope
  const dialogBaseline = useRef<string | null>(null)
  const generation = useRef(0)
  const dialogSignature = JSON.stringify({label,identity,gap,dateStart,anchor,notes,timezone,narrowPosition,narrowSync,family,uncertainUntil,copyScopes,copyApparatus,copyHeight,otherCode,trackName,endDate})
  useEffect(() => { dialogBaseline.current = panel ? dialogSignature : null }, [panel])
  const contextKey = JSON.stringify(context)
  const familyCode = context.code.startsWith('5') ? context.code.slice(0, 2) : context.code.slice(0, 1)
  const canFamily = ['1','2','3','4','51','52','53','54'].includes(familyCode)
  const active = episodes.find(e => e.id === pair[0])
  const visibleEpisodes = episodes.filter(e => (!e.apparatus || e.apparatus === context.apparatus) && (!e.height || e.height === context.height) && (e.scope === context.code || e.scope === familyCode) && (e.position == null || e.position === context.position) && (e.sync == null || e.sync === context.sync))
  const compatible = visibleEpisodes.filter(e => !e.gap).sort((a,b) => a.start_at.localeCompare(b.start_at) || a.id - b.id)
  const chronologicalPair = (ids: number[]) => [...ids].sort((a,b) => { const left = episodes.find(e => e.id === a), right = episodes.find(e => e.id === b); return (left?.start_at ?? '').localeCompare(right?.start_at ?? '') || a-b })
  const currentEpisode = [...visibleEpisodes].filter(e => Date.parse(`${e.start_at}Z`) <= Date.now() && (!e.end_at || Date.parse(`${e.end_at}Z`) > Date.now())).sort((a, b) =>
    Number(b.scope === context.code) - Number(a.scope === context.code)
    || (Number(b.position != null) + Number(b.sync != null)) - (Number(a.position != null) + Number(a.sync != null))
    || b.start_at.localeCompare(a.start_at))[0]
  const uniqueTechniques = episodes.filter((e, i, all) => e.technique_id && all.findIndex(other => other.technique_id === e.technique_id) === i)
  const base = `/api/v1/technique-history/${diver}`
  useEffect(() => {
    const g = ++generation.current
    setSetupReady(false); setSetup(false); setPanel(null); setComparing(false); setNotice(''); setLabel(''); setIdentity(null); setEdit(null); setDateStart(''); setUncertainUntil(''); setAnchor(null); setCopyPreview(null); setBusy(false); setPair([]); setAfter(0); setEpisodeAfter(0); setTrackAfter(0); setTracks([]); setTrack(null); setEpisodes([]); setAttempts([]); setSelected([]); setPreview(null); setError('')
    api.get('/api/v1/technique-history/preferences').then(({ data }) => { if (g === generation.current) setTimezone(data.timezone) }).catch(() => {})
    api.get(`${base}/tracks`).then(({ data }) => { if (g === generation.current) { setTrackNext(data.next); setTracks(data.items); setTrack(data.items[0]?.id ?? null);if(!data.items.length)setSetupReady(true) } }).catch(() => { if (g === generation.current) setError(t('technique.unavailable')) })
    return () => { generation.current++ }
  }, [base, contextKey, t])
  useEffect(() => {
    if (!track) return
    const g = ++generation.current
    setCopyPreview(null); setPreview(null); setSelected([]); setError('')
    Promise.all([api.get(`${base}/${track}/episodes?after=${episodeAfter}`), api.post(`${base}/${track}/attempts`, { ...context, after, session_id: sessionFilter ? Number(sessionFilter) : null, timezone, from_date: fromFilter || null, to_date: toFilter || null })]).then(([e, a]) => {
      if (g !== generation.current) return
      if (e.data.revision !== a.data.revision) { setError(t('technique.conflict')); return }
      setEpisodeNext(e.data.next); setEpisodes(e.data.items); setRevision(e.data.revision); setAttempts(a.data.items); setNext(a.data.next);setSetupReady(true)
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
      else { if (path === 'changes') void api.post('/api/v1/technique-history/preferences', { timezone }).catch(() => {}); setPreview(null); setEdit(null); setLabel(''); setIdentity(null); setPanel(null); setNotice(t('technique.saved')); setReload(v => v + 1) }
    } catch { if (g === generation.current) setError(t('technique.conflict')) }
    finally { if (g === generation.current) setBusy(false) }
  }
  function requestClosePanel() {
    if (dialogBaseline.current !== null && dialogBaseline.current !== dialogSignature && !window.confirm(t('technique.discardChanges'))) return
    closePanel()
  }
  function closePanel() { setPanel(null); setPreview(null); setCopyPreview(null); setError('') }
  useEffect(()=>{try{setHasDraft(Boolean(localStorage.getItem(`technique-draft:${viewer??'local'}:${base}/${track}:${JSON.stringify(context)}:new`)))}catch{setHasDraft(false)}},[setup,viewer,base,track,contextKey])
  async function startSetup(episode?: Episode) {
    setSetupEpisode(episode); setPanel(null)
    setError(''); setNotice('')
    if (!tracks.length) {
      const g = generation.current; setBusy(true)
      try { const { data } = await api.post(`${base}/tracks`, { name: 'General' }); if (g !== generation.current) return; setTracks([data]); setTrack(data.id) }
      catch { if (g === generation.current) setError(t('technique.conflict')); return }
      finally { if (g === generation.current) setBusy(false) }
    }
    setSetup(true)
  }
  async function newChange() {
    setError(''); setNotice(''); setEdit(null); setLabel(''); setIdentity(null); setGap(false); setFamily(false); setNotes(''); setAnchor(null)
    setDateStart(techniqueInputDate(new Date(), timezone)); setUncertainUntil(''); setNarrowPosition(true); setNarrowSync(true); setPreview(null)
    if (!tracks.length) {
      const g = generation.current; setBusy(true)
      try { const { data } = await api.post(`${base}/tracks`, { name: 'General' }); if (g !== generation.current) return; setTracks([data]); setTrack(data.id) }
      catch { if (g === generation.current) setError(t('technique.conflict')); return }
      finally { if (g === generation.current) setBusy(false) }
    }
    setPanel('change')
  }
  function editEpisode(e: Episode) {
    setNarrowPosition(e.position != null); setNarrowSync(e.sync != null); setEdit(e.id)
    setDateStart(techniqueInputDate(new Date(`${e.start_at}Z`), timezone)); setAnchor(null); setLabel(e.label ?? ''); setIdentity(e.technique_id)
    setGap(e.gap); setFamily(e.scope !== context.code); setNotes(e.notes ?? ''); setUncertainUntil(e.uncertain_until ? techniqueInputDate(new Date(`${e.uncertain_until}Z`), timezone) : ''); setPreview(null); setPanel('change')
  }
  async function deleteEpisode(e: Episode) {
    const g = generation.current
    try {
      const { data } = await api.post(`${base}/${track}/episodes/${e.id}/delete`, { revision })
      if (g === generation.current && window.confirm(`${t('technique.deletePreview')}\n${techniqueImpact(t, data.preview.eligible, data.preview.explicit_preserved)}`)) void mutate(`episodes/${e.id}/delete`, { revision, commit: true })
    } catch { if (g === generation.current) setError(t('technique.conflict')) }
  }
  return <section className="ca-panel th-history" aria-label={t('technique.title')}>
    <header className="th-header">
      <h2>{t('technique.title')}</h2>
      <button className="th-icon" type="button" aria-label={t('technique.manage')} onClick={() => setPanel('manage')}><SlidersHorizontal size={18} /></button>
    </header>
    {error && !panel && <p className="th-error" role="alert">{error}</p>}
    {notice && <p className="th-notice" role="status"><Check size={15} />{notice}</p>}
    <div className="th-setup-entry"><button className="th-primary" disabled={busy||!setupReady} onClick={() => void startSetup()}><ListChecks size={17} />{t(hasDraft?'technique.resumeHistory':'technique.setupEntry')}</button></div>
    {!!tracks.length && <div className="th-toolbar">
      {tracks.length > 1 ? <select className="th-track-select" aria-label={t('technique.track')} value={track ?? ''} onChange={e => { setTrack(Number(e.target.value)); setPair([]); setComparing(false); setAfter(0); setEpisodeAfter(0); setBusy(false) }}>{tracks.map(r => <option key={r.id} value={r.id}>{r.name === 'General' ? t('technique.general') : r.name}</option>)}</select> : <span className="th-track-name">{tracks[0].name === 'General' ? t('technique.general') : tracks[0].name}</span>}
      {compatible.length >= 2 && <button className="th-text-button" aria-pressed={comparing} onClick={() => { setComparing(v => !v); setPair(comparing ? [] : compatible.slice(-2).map(e => e.id)) }}><ArrowLeftRight size={15} />{comparing ? t('technique.done') : t('technique.compare')}</button>}
    </div>}
    {!!visibleEpisodes.length && !comparing && chartActive && <TechniqueTrackChart base={`${base}/${track}`} context={context} revision={revision} selected={pair[0]} selection={visibleEpisodes.find(e => e.id === pair[0])} onClear={() => setPair([])} onSelect={id => setPair([id])} />}
    {comparing ? <div className="th-comparing">
      <div className="th-compare-pickers">{[0, 1].map(index => <label className="th-field" key={index}>{t(index ? 'technique.after' : 'technique.before')}<select value={pair[index] ?? ''} onChange={e => setPair(p => { const n = [...p]; n[index] = Number(e.target.value); return chronologicalPair(n) })}>{compatible.filter(e => e.id !== pair[1 - index]).map(e => <option key={e.id} value={e.id}>{e.label} — {visibleEpisodes.some(other => other.id !== e.id && other.start_at.slice(0,10) === e.start_at.slice(0,10)) ? techniqueDateTime(e.start_at,i18n.language) : date(e.start_at)}</option>)}</select></label>)}</div>
      <TechniqueComparison onTrack={(id, name) => { setTracks(p => p.some(t => t.id === id) ? p : [...p, { id, name: name ?? t('technique.general'), revision: 0 }]); setTrack(id); setPair([]); setComparing(false); setAfter(0); setEpisodeAfter(0) }} base={`${base}/${track}`} context={context} pair={pair} revision={revision} />
    </div> : <>
      {!visibleEpisodes.length && <div className="th-empty"><span className="th-empty-line" aria-hidden="true"><i /><i /><i /></span><h3>{t('technique.emptyTitle')}</h3><p>{t('technique.periodsNotDives')}</p></div>}
      <ol className="th-timeline">{[...visibleEpisodes].reverse().map(e => <li key={e.id} className={pair[0] === e.id ? 'is-selected' : ''}>
        <button className="th-episode" aria-pressed={pair[0] === e.id} onClick={() => setPair(p => p[0] === e.id ? [] : [e.id])}>
          <span className="th-timeline-dot" aria-hidden="true" />
          <span className="th-episode-copy"><span className="th-episode-name">{e.label ?? t('technique.unknown')}{e.id === currentEpisode?.id && <span className="th-current">{t('technique.current')}</span>}</span><span className="th-date">{periodDate(e.start_at,e.end_at)}{e.end_at ? ` – ${periodDate(e.end_at,e.start_at)}` : ` – ${t('technique.now')}`}{e.uncertain_until ? ` ≈ ${date(e.uncertain_until)}` : ''}</span></span><ChevronRight size={16} aria-hidden="true" />
        </button>
        <div className={`th-episode-reveal${pair[0] === e.id ? ' is-open' : ''}`} aria-hidden={pair[0] !== e.id} ref={node => node?.toggleAttribute('inert', pair[0] !== e.id)}><div className="th-episode-clip"><div className="th-episode-actions">{e.anchor_id && e.scope === context.code && !e.gap && <button onClick={() => void startSetup(e)}>{t('technique.adjustInPlayer')}</button>}<button onClick={() => editEpisode(e)}><Pencil size={14} />{t('technique.edit')}</button><button onClick={() => { setCopyPreview(null); setPanel('share') }}><Share2 size={14} />{t('technique.share')}</button></div></div></div>
      </li>)}</ol>
    </>}
    {(episodeAfter > 0 || episodeNext != null) && <div className="th-pagination">{episodeAfter > 0 && <button onClick={() => setEpisodeAfter(0)}>{t('common.back')}</button>}{episodeNext != null && <button onClick={() => setEpisodeAfter(episodeNext!)}>{t('technique.nextPeriods')}</button>}</div>}

    {setup && track != null && createPortal(<TechniqueSetup trackName={tracks.find(item=>item.id===track)?.name==='General'?t('technique.general'):tracks.find(item=>item.id===track)?.name} viewer={viewer} key={`${base}/${track}/${contextKey}/${setupEpisode?.id ?? 'new'}`} onAdjust={episode => setSetupEpisode(episode)} base={`${base}/${track}`} context={context} revision={revision} timezone={timezone} initialEpisode={setupEpisode} constrainPosition={setupEpisode ? setupEpisode.position != null : true} constrainSync={setupEpisode ? setupEpisode.sync != null : true} onClose={() => setSetup(false)} onDone={() => { setSetup(false); setReload(n => n + 1); setNotice(t('technique.saved')) }} />, document.body)}

    {panel === 'change' && <TechniqueDialog title={t(preview ? 'technique.reviewChange' : edit ? 'technique.editChange' : 'technique.enable')} onClose={requestClosePanel}>
      {error && <p className="th-error" role="alert">{error}</p>}
      {preview ? <div className="th-review">
        <h3>{label || uniqueTechniques.find(e => e.technique_id === identity)?.label || t('technique.unknown')}</h3>
        <dl><div><dt>{t('technique.from')}</dt><dd>{date(String(preview.start_at))}</dd></div><div><dt>{t('technique.appliesTo')}</dt><dd>{String(preview.scope)} · {context.height}</dd></div></dl>
        <p>{techniqueImpact(t, planSummary?.counts?.affected ?? 0, planSummary?.counts?.explicit_preserved ?? 0)}</p>
        {planSummary?.upcoming && <p>{t('technique.nextChange', { date: date(planSummary.upcoming.start_at) })}</p>}
        <div className="th-dialog-actions"><button className="th-secondary" onClick={() => setPreview(null)}>{t('technique.backToEdit')}</button><button className="th-primary" disabled={busy} onClick={() => void mutate('changes', preview)}>{t('technique.saveChange')}</button></div>
      </div> : <form className="th-form" onSubmit={e => { e.preventDefault(); const a = attempts.find(a => a.id === anchor); if (a || dateStart) void mutate('preview', { ...context, revision, label, notes, timezone, constrain_position: narrowPosition, constrain_sync: narrowSync, technique_id: identity, episode_id: edit, gap, scope: family ? familyCode : context.code, start_at: a?.history_occurred_at ?? dateStart, anchor_id: a?.id, uncertain_until: uncertainUntil || null, precision: uncertainUntil ? 'approximate' : a ? 'attempt' : 'date' }) }}>
        <label className="th-field">{t('technique.whatChanged')}<input autoFocus readOnly={Boolean(edit && identity)} maxLength={120} required={!gap && identity === null} value={label} placeholder={t('technique.labelExample')} onChange={e => { setLabel(e.target.value); setIdentity(null) }} /></label>
        {edit && identity && <button type="button" className="th-text-button" onClick={() => setIdentity(null)}>{t('technique.useDifferentTechnique')}</button>}
        <label className="th-field">{t('technique.from')}<input type="datetime-local" required={!anchor} value={dateStart} onChange={e => { setDateStart(e.target.value); setAnchor(null) }} /></label>
        <details className="th-details"><summary>{t('technique.options')}</summary><div className="th-form">
          <label className="th-field">{t('technique.start')}<select value={anchor ?? ''} onChange={e => setAnchor(e.target.value ? Number(e.target.value) : null)}><option value="">{t('technique.useDate')}</option>{attempts.map(a => <option key={a.id} value={a.id}>{techniqueDateTime(a.dive_datetime, i18n.language)}{a.session_index && a.session_total ? ` · ${t('technique.sessionAttempt', { index: a.session_index, total: a.session_total })}` : ''}</option>)}</select></label>
          <label className="th-field">{t('technique.approximate')}<input type="datetime-local" value={uncertainUntil} onChange={e => setUncertainUntil(e.target.value)} /></label>
          <label className="th-field">{t('technique.reuse')}<select value={identity ?? ''} onChange={e => setIdentity(e.target.value ? Number(e.target.value) : null)}><option value="">{t('technique.newTechnique')}</option>{uniqueTechniques.map(e => <option key={e.technique_id} value={e.technique_id!}>{e.label}</option>)}</select></label>
          <label className="th-check"><input type="checkbox" checked={gap} onChange={e => setGap(e.target.checked)} />{t('technique.unknownPeriod')}</label>
          {canFamily && <label className="th-check"><input type="checkbox" checked={family} onChange={e => setFamily(e.target.checked)} />{t('technique.family', { family: familyCode })}</label>}
          <label className="th-check"><input type="checkbox" checked={narrowPosition} onChange={e => setNarrowPosition(e.target.checked)} />{t('technique.onlyPosition', { position: context.position })}</label>
          <label className="th-check"><input type="checkbox" checked={narrowSync} onChange={e => setNarrowSync(e.target.checked)} />{t(context.sync ? 'technique.onlySync' : 'technique.onlyIndividual')}</label>
          <label className="th-field">{t('technique.timezone')}<input maxLength={80} value={timezone} onChange={e => setTimezone(e.target.value)} /></label>
          <label className="th-field">{t('technique.notes')}<textarea maxLength={2000} rows={3} value={notes} onChange={e => setNotes(e.target.value)} /></label>
        </div></details>
        <div className="th-dialog-actions"><button type="button" className="th-secondary" onClick={requestClosePanel}>{t('technique.cancel')}</button><button className="th-primary" disabled={busy}>{t('technique.reviewChange')}</button></div>
      </form>}
    </TechniqueDialog>}

    {panel === 'manage' && <TechniqueDialog title={t('technique.manage')} onClose={requestClosePanel}>
      {error && <p className="th-error" role="alert">{error}</p>}
      <div className="th-form"><button className="th-text-button" onClick={()=>void newChange()}>{t('technique.useDateInstead')}</button><h3>{t('technique.topics')}</h3><div className="th-topic-list">{tracks.map(r => <button key={r.id} className={track === r.id ? 'is-selected' : ''} onClick={() => { setTrack(r.id); setPair([]); setComparing(false); setAfter(0); setEpisodeAfter(0); closePanel() }}>{r.name === 'General' ? t('technique.general') : r.name}{track === r.id && <Check size={16} />}</button>)}</div>
      {(trackAfter > 0 || trackNext != null) && <div className="th-pagination">{trackAfter > 0 && <button onClick={async () => { const g = generation.current; const { data } = await api.get(`${base}/tracks`); if (g === generation.current) { setTrackAfter(0); setTracks(data.items); setTrackNext(data.next) } }}>{t('common.back')}</button>}{trackNext != null && <button onClick={async () => { const g = generation.current; const { data } = await api.get(`${base}/tracks?after=${trackNext}`); if (g === generation.current) { setTrackAfter(trackNext!); setTracks(data.items); setTrackNext(data.next) } }}>{t('technique.moreTracks')}</button>}</div>}
      <form className="th-inline-form" onSubmit={async e => { e.preventDefault(); const g = generation.current; try { const { data } = await api.post(`${base}/tracks`, { name: trackName }); if (g === generation.current) { setTracks(p => [...p, data]); setTrack(data.id); setTrackName(''); setPair([]); setComparing(false); closePanel() } } catch { if (g === generation.current) setError(t('technique.conflict')) } }}><label className="th-field">{t('technique.newTopic')}<input required maxLength={80} value={trackName} placeholder={t('technique.topicExample')} onChange={e => setTrackName(e.target.value)} /></label><button className="th-secondary">{t('technique.add')}</button></form>
      {!!tracks.length && <button className="th-secondary" onClick={() => { setChartActive(v => !v); setPair([]); setComparing(false); closePanel() }}>{t(chartActive ? 'technique.showAllScores' : 'technique.showTechniqueScores')}</button>}
      {!!tracks.length && <button className="th-secondary" onClick={() => setPanel('log')}><ListChecks size={16} />{t('technique.tagDives')}</button>}
      {active && <details className="th-details"><summary>{t('technique.periodSettings')}</summary><div className="th-form"><h3>{active.label}</h3><button className="th-secondary" onClick={() => editEpisode(active)}>{t('technique.editChange')}</button>
        <label className="th-field">{t('technique.endUtc')} · {timezone}<input type="datetime-local" value={endDate} onChange={e => setEndDate(e.target.value)} /></label><button className="th-secondary" disabled={!endDate || busy} onClick={async () => { const g = generation.current; const body = { revision, episode_id: active.id, timezone, end_at: endDate }; try { await api.post(`${base}/${track}/end`, body); if (g === generation.current && window.confirm(t('technique.endConfirm'))) void mutate('end', { ...body, commit: true }) } catch { if (g === generation.current) setError(t('technique.conflict')) } }}>{t('technique.end')}</button>
        <label className="th-field">{t('technique.rename')}<input maxLength={120} value={label} onChange={e => setLabel(e.target.value)} /></label><button className="th-secondary" disabled={!label || busy} onClick={() => { if (active.technique_id) void mutate(`techniques/${active.technique_id}/rename`, { revision, label }) }}>{t('common.save')}</button>
        <button className="th-danger" disabled={busy} onClick={() => void deleteEpisode(active)}>{t('technique.delete')}</button>
      </div></details>}
      {!!tracks.length && <button className="th-text-button" disabled={busy} onClick={() => { if (window.confirm(t('technique.undoConfirm'))) void mutate('undo', { revision }) }}>{t('technique.undoLast')}</button>}
      </div>
    </TechniqueDialog>}

    {panel === 'log' && <TechniqueDialog title={t('technique.tagDives')} onClose={requestClosePanel}>
      {error && <p className="th-error" role="alert">{error}</p>}
      <details className="th-details"><summary>{t('technique.filters')}</summary><div className="th-form"><label className="th-field">{t('technique.session')}<select value={sessionFilter} onChange={e => { setSessionFilter(e.target.value); setAfter(0) }}><option value="">{t('technique.allSessions')}</option>{[...new Set(attempts.map(a => a.session_id))].filter(Boolean).map(id => <option key={id} value={id}>{date(attempts.find(a => a.session_id === id)!.dive_datetime)}</option>)}</select></label><label className="th-field">{t('technique.fromUtc')} · {timezone}<input type="datetime-local" value={fromFilter} onChange={e => { setFromFilter(e.target.value); setAfter(0) }} /></label><label className="th-field">{t('technique.toUtc')} · {timezone}<input type="datetime-local" value={toFilter} onChange={e => { setToFilter(e.target.value); setAfter(0) }} /></label></div></details>
      <div className="th-log-toolbar"><button className="th-text-button" onClick={() => setSelected(attempts.map(a => a.id))}>{t('technique.selectPage')}</button>{selected.length >= 2 && <button className="th-text-button" onClick={() => { const indices = selected.map(id => attempts.findIndex(a => a.id === id)).filter(i => i >= 0); setSelected(attempts.slice(Math.min(...indices), Math.max(...indices) + 1).map(a => a.id)) }}>{t('technique.selectRange')}</button>}</div>
      <fieldset className="th-attempts"><legend className="sr-only">{t('technique.recorded')}</legend>{attempts.map(a => <label key={a.id} className="th-attempt"><input type="checkbox" checked={selected.includes(a.id)} onChange={e => setSelected(p => e.target.checked ? [...p, a.id] : p.filter(id => id !== a.id))} /><span className="th-attempt-thumb"><DiveThumbnail dive={a} compact /></span><span><strong>{date(a.dive_datetime)}</strong><small>{a.use_label ?? t(`technique.${a.state}`)}</small>{a.dive_datetime !== a.history_occurred_at && <small>{t('technique.historyOrder')}: {date(a.history_occurred_at)}</small>}{a.recorded_episode_deleted && <small>{t('technique.deletedPeriod')}</small>}{a.late_import && <small>{t('technique.lateImport')}</small>}</span></label>)}</fieldset>
      {(after > 0 || next != null) && <div className="th-pagination">{after > 0 && <button onClick={() => setAfter(0)}>{t('common.back')}</button>}{next != null && <button onClick={() => setAfter(next!)}>{t('technique.next')}</button>}</div>}
      {!!selected.length && <div className="th-tag-bar"><strong>{t('technique.selectedDives', { count: selected.length })}</strong><select aria-label={t('technique.recorded')} value="" disabled={busy} onChange={e => { if (e.target.value) void mutate('assign', { ...context, revision, ids: selected, state: 'technique', technique_id: Number(e.target.value) }) }}><option value="">{t('technique.chooseTechnique')}</option>{uniqueTechniques.map(e => <option key={e.technique_id} value={e.technique_id!}>{e.label}</option>)}</select><div className="th-action-row">{(['mixed', 'unknown'] as const).map(state => <button key={state} className="th-secondary" disabled={busy} onClick={() => void mutate('assign', { ...context, revision, ids: selected, state })}>{t(`technique.${state}`)}</button>)}</div></div>}
      <details className="th-details"><summary>{t('technique.markSession')}</summary><div className="th-form">{[...new Set(attempts.map(a => (a as Attempt & { session_id: number }).session_id))].filter(Boolean).map(session => <div className="th-session" key={session}><span>{date(attempts.find(a => a.session_id === session)!.dive_datetime)}</span><div>{(['mixed', 'unknown'] as const).map(state => <button className="th-text-button" key={state} disabled={busy} onClick={() => void mutate('session-state', { ...context, revision, session_id: session, state })}>{t(`technique.${state}`)}</button>)}</div></div>)}</div></details>
      {selected.length === 1 && <details className="th-details"><summary>{t('technique.correctDate')}</summary><div className="th-form"><label className="th-field">{t('technique.date')}<input type="datetime-local" value={endDate} onChange={e => setEndDate(e.target.value)} /></label><button className="th-secondary" disabled={!endDate || busy} onClick={async () => { const g = generation.current; const body = { revision, attempt_id: selected[0], timezone, occurred_at: endDate }; try { const { data } = await api.post(`${base}/${track}/correct-order`, body); if (g === generation.current && window.confirm(`${t('technique.correctOrder')} · ${data.preview.affected_attempts}`)) void mutate('correct-order', { ...body, track_revisions: data.preview.track_revisions, commit: true }) } catch { if (g === generation.current) setError(t('technique.conflict')) } }}>{t('technique.preview')}</button></div></details>}
    </TechniqueDialog>}

    {panel === 'share' && active && <TechniqueDialog title={t('technique.share')} onClose={requestClosePanel}>
      {error && <p className="th-error" role="alert">{error}</p>}
      <h3 className="th-share-name">{active.label}</h3>
      <form className="th-form" onSubmit={async e => { e.preventDefault(); if (!copyScopes) { setError(t('technique.invalidCode')); return } const body = { revision, episode_id: active.id, targets: copyScopes.split(',').filter(Boolean).map(scope => ({ scope: scope.trim(), apparatus: copyApparatus, height: copyHeight })) }; const g = generation.current; try { const { data } = await api.post(`${base}/${track}/copy`, body); if (g === generation.current) { setCopyPreview(body); setCopyDetails(data.targets) } } catch { if (g === generation.current) setError(t('technique.conflict')) } }}>
        <label className="th-field">{t('technique.alsoApply')}<select value="" onChange={e => { if (e.target.value) setCopyScopes([...new Set([...copyScopes.split(',').filter(Boolean),e.target.value])].join(',')); setCopyPreview(null) }}><option value="">{t('technique.chooseScope')}</option>{[context.code,'1','2','3','4','51','52','53','54'].map(scope => <option key={scope} value={scope}>{scopeLabel(scope)}</option>)}</select></label>
        <div className="th-scope-chips">{copyScopes.split(',').filter(Boolean).map(scope => <button className="th-secondary" key={scope} type="button" aria-label={t('technique.removeScope',{name:scopeLabel(scope)})} onClick={() => {setCopyScopes(copyScopes.split(',').filter(s => s !== scope).join(','));setCopyPreview(null)}}>{scopeLabel(scope)} ×</button>)}</div>
        <div className="th-inline-form"><label className="th-field">{t('technique.otherCode')}<input maxLength={5} placeholder="5132D" value={otherCode} onChange={e => setOtherCode(e.target.value.toUpperCase())} /></label><button className="th-secondary" type="button" disabled={!otherCode} onClick={() => { if (!/^[1-6][0-9]{2,3}[ABCD]?$/.test(otherCode)) {setError(t('technique.invalidCode'));return} setCopyScopes([...new Set([...copyScopes.split(',').filter(Boolean),otherCode])].join(','));setOtherCode('');setCopyPreview(null) }}>{t('technique.addCode')}</button></div>
        <div className="th-field-pair"><label className="th-field">{t('technique.apparatus')}<select value={copyApparatus} onChange={e => { setCopyApparatus(e.target.value); setCopyPreview(null) }}><option value="springboard">{t('technique.springboard')}</option><option value="platform">{t('technique.platform')}</option></select></label><label className="th-field">{t('attemptDetail.height')}<input required maxLength={5} value={copyHeight} onChange={e => { setCopyHeight(e.target.value); setCopyPreview(null) }} /></label></div>
        <button className="th-secondary" disabled={busy}>{t('technique.reviewChange')}</button>
      </form>
      {copyPreview && <div className="th-review"><ul>{copyDetails.map(d => <li key={d.scope.scope}><strong>{d.scope.scope}</strong><p>{techniqueImpact(t, d.counts?.affected ?? 0, d.counts?.explicit_preserved ?? 0)}</p>{d.upcoming && <p>{t('technique.nextChange', { date: date(d.upcoming.start_at) })}</p>}</li>)}</ul><button className="th-primary" disabled={busy} onClick={() => { void mutate('copy', { ...copyPreview, commit: true }); setCopyPreview(null) }}>{t('technique.copyChange')}</button></div>}
    </TechniqueDialog>}
  </section>
}
