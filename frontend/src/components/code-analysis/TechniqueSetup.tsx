import TechniqueSessionBrowser, { type TechniqueSession } from './TechniqueSessionBrowser'
import { techniqueImpact } from './techniqueText'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Flag, Pencil, Trash2 } from 'lucide-react'
import ClipViewer from '../clip-viewer/ClipViewer'
import TechniqueDialog from './TechniqueDialog'
import { techniqueDateTime } from './techniqueDates'
import { api } from '../../services/api'
import type { Attempt } from '../../utils/attemptPresentation'

type Context = { code: string; apparatus: string; height: string; position: string; sync: boolean }
export type SetupEpisode = { start_at?:string; id: number; anchor_id?: number | null; technique_id: number | null; label: string | null; scope: string; position?: string | null; sync?: boolean | null; notes?: string; uncertain_until?: string | null }
export type AdjustmentChoice = SetupEpisode & {start_at:string;end_at:string|null;track_id:number}
type Impact = { draft_key?:string; anchor_id: number; end_at: string | null; end_id: number | null; counts: { affected: number; explicit_preserved: number }; replaces: string | null; same_previous?: boolean; same_following?: boolean; next_label?: string | null; following: { id: number; label: string | null; start_at: string } | null }
type HistoryAttempt = { history_total?: number; history_index?: number; intended_scope?: string | null; episode_id?: number | null; intended_start_at?: string | null; intended_start_id?: number | null; session_index?: number; session_total?: number; intended_label?: string | null; id: number; session_id: number; dive_code: string; dive_datetime: string; history_occurred_at: string; video_uuid?: string | null; performance: string }
type Marker = { attempt: HistoryAttempt; label: string; saved: boolean; identityKey: string; techniqueId?: number; uncertainUntil?: string; sessionStart?: boolean; replaceEpisode?: number; replaceDraft?: string; replaceLabel?:string }
const ordered = (markers: Marker[]) => [...markers].sort((a, b) => a.attempt.history_occurred_at.localeCompare(b.attempt.history_occurred_at) || a.attempt.id - b.attempt.id)

/** Reuses the Library's player/gesture owner. Only a 100-clip navigation window
 * and at most 16 pending boundaries are retained; dates can seek the full history. */
export default function TechniqueSetup({ base, context, revision, constrainPosition, constrainSync, onClose, onDone, onAdjust, initialEpisode, independent, trackName = '', timezone = 'UTC', startInSessions = true, viewer = 'local' }: {
  independent?:{base:string;revision:number;choices:AdjustmentChoice[];more?:boolean;onMore?:()=>void}; trackName?: string; startInSessions?: boolean; viewer?: string | number; onAdjust?: (episode: SetupEpisode) => void; initialEpisode?: SetupEpisode; timezone?: string; base: string; context: Context; revision: number; constrainPosition: boolean; constrainSync: boolean; onClose: () => void; onDone: () => void
}) {
  const { t, i18n } = useTranslation()
  const independentVersion=useRef(independent?.revision??0)
  const [replacement,setReplacement]=useState('')
  const [replacementChoice,setReplacementChoice]=useState<{id:number;label:string|null}|null>(null)
  const editingDraftKey=useRef<string|null>(null)
  const storageKey = `${independent?'adjustment-draft':'technique-draft'}:${viewer}:${base}:${JSON.stringify(context)}:${initialEpisode?.id ?? 'new'}`
  const [sessionsOpen,setSessionsOpen] = useState(startInSessions && !initialEpisode)
  const [browsePage,setBrowsePage]=useState({month:'',after:0})
  const [activeSession,setActiveSession] = useState<number|null>(null)
  const [returnToSessions,setReturnToSessions] = useState(false)
  const [uncertainUntil,setUncertainUntil] = useState<string|undefined>()
  const [nameDraft,setNameDraft]=useState('')
  const [removedMarker,setRemovedMarker]=useState<Marker|null>(null)
  const [draftReady,setDraftReady] = useState(false)
  const [items, setItems] = useState<HistoryAttempt[]>([])
  const [current, setCurrent] = useState<HistoryAttempt | null>(null)
  const [next, setNext] = useState<number | null>(null)
  const [previous, setPrevious] = useState<number | null>(null)
  const [authError, setAuthError] = useState(false)
  const [loading, setLoading] = useState(true), [error, setError] = useState('')
  const [seek, setSeek] = useState(''), [showSeek, setShowSeek] = useState(false)
  const [rate, setRate] = useState(1)
  const [markers, setMarkers] = useState<Marker[]>([])
  const [identities, setIdentities] = useState<{ id: number; label: string }[]>([])
  const [identityNext, setIdentityNext] = useState<number | null>(null)
  const [selectedIdentity, setSelectedIdentity] = useState('new')
  const [movingKey, setMovingKey] = useState<string | null>(null)
  const [editing, setEditing] = useState<HistoryAttempt | null>(null), [label, setLabel] = useState('')
  const [review, setReview] = useState(false), [saving, setSaving] = useState(false)
  const [reviewed, setReviewed] = useState(false)
  const [errorKind, setErrorKind] = useState<'revision' | 'retry' | 'validation' | null>(null)
  const [impacts, setImpacts] = useState<Impact[]>([])
  const identitySerial = useRef(0)
  const appliedSeek = useRef('')
  const version = useRef(revision), alive = useRef(true), epoch = useRef(0), fetching = useRef(false)
  const controller = useRef<AbortController | null>(null)
  const date = (value: string) => techniqueDateTime(value, i18n.language)
  const draft = ordered(markers)
  const pending = draft.filter(m => !m.saved)
  const markerKey=(marker:Marker)=>`${marker.identityKey}:${marker.attempt.id}`
  const change = (marker: Marker, rev: number) => ({ draft_key:markerKey(marker),replace_episode_id:marker.replaceEpisode,replace_draft_key:marker.replaceDraft, ...context, revision: rev, technique_id: marker.techniqueId, draft_identity: marker.identityKey, label: marker.label, scope: initialEpisode?.scope ?? context.code, episode_id: initialEpisode?.id, notes: initialEpisode?.notes ?? '', uncertain_until: marker.uncertainUntil ?? initialEpisode?.uncertain_until ?? null, anchor_id: marker.attempt.id, start_at: marker.attempt.history_occurred_at, precision: marker.uncertainUntil ? 'approximate' : 'attempt', timezone: 'UTC', constrain_position: constrainPosition, constrain_sync: constrainSync })

  async function loadIdentities(after = 0) {
    const generation = epoch.current
    try {
      const { data } = await api.get(`${base}/techniques`, { params: { after } })
      if (!alive.current || generation !== epoch.current) return
      setIdentities(previous => { const chosen = previous.find(item => `id:${item.id}` === selectedIdentity); return chosen && !data.items.some((item: { id: number }) => item.id === chosen.id) ? [chosen, ...data.items] : data.items }); setIdentityNext(data.next)
    } catch { /* Existing choices stay available; users can retry loading them explicitly. */ }
  }
  async function load(after: number, replace = false, from = '', direction: 'after' | 'before' | 'around' = 'after', focusId?: number, sessionId: number|null = activeSession) {
    if (fetching.current && !replace) return
    if (direction === 'around' || from) setActiveSession(null)
    if (replace) { controller.current?.abort(); epoch.current++; appliedSeek.current = ''; setCurrent(null) }
    const generation = epoch.current
    const abort = new AbortController(); controller.current = abort
    fetching.current = true; setLoading(true); setAuthError(false); setError(''); setErrorKind(null)
    try {
      const { data } = await api.post(`${base}/attempts`, { ...context, after: direction === 'after' ? after : 0, before: direction === 'before' ? after : 0, around: direction === 'around' ? after : 0, session_id:direction === 'around' || from ? null : sessionId, seek_at: from ? from.includes('T') ? from : `${from}T00:00:00` : null, timezone }, { signal: abort.signal })
      if (!alive.current || generation !== epoch.current) return
      if (data.revision !== version.current) { setErrorKind('revision'); setError(t('technique.conflict')); return }
      const rows: HistoryAttempt[] = data.items
      if (focusId && !rows.some(row => row.id === focusId)) { setError(t('technique.anchorUnavailable')); return }
      setItems(existing => {
        if (replace) return rows
        const unique = [...new Map((direction === 'before' ? [...rows, ...existing] : [...existing, ...rows]).map(row => [row.id, row])).values()]
        const retained = direction === 'before' ? unique.slice(0,100) : unique.slice(-100)
        if (current && !retained.some(row => row.id === current.id)) setCurrent(direction === 'before' ? rows[rows.length - 1] : rows[0])
        if (unique.length > 100) {
          if (direction === 'before') setNext(retained[retained.length - 1].id)
          else setPrevious(retained[0].id)
        }
        return retained
      })
      if (replace) { setCurrent(rows.find(row => row.id === (focusId ?? data.focus_id)) ?? rows[0] ?? null); setPrevious(data.previous ?? null); setNext(data.next); if (initialEpisode && !markers.length && rows.length) { const first = rows.find(row => row.id === initialEpisode.anchor_id) ?? (!initialEpisode.anchor_id ? rows.find(row=>row.id===data.focus_id) ?? rows[0] : undefined); if (first) { const key = `id:${initialEpisode.technique_id}`; setMarkers([{ attempt: first, label: initialEpisode.label ?? '', identityKey: key, techniqueId: initialEpisode.technique_id ?? undefined, saved: false }]); setMovingKey(`${key}:${first.id}`) } } }
      else if (direction === 'before') setPrevious(data.previous ?? null)
      else setNext(data.next)
    } catch (failure) { if (alive.current && generation === epoch.current && !abort.signal.aborted) { const expired = (failure as { response?: { status?: number } }).response?.status === 401; setAuthError(expired); setErrorKind('retry'); setError(t(expired ? 'technique.sessionExpired' : 'technique.unavailable')) } }
    finally { if (alive.current && generation === epoch.current) { fetching.current = false; setLoading(false) } }
  }
  useEffect(() => {
    alive.current = true
    try {
      const saved=JSON.parse(localStorage.getItem(storageKey)??'null')
      if(Array.isArray(saved?.markers) && saved.markers.length<=16 && saved.markers.every((m:Marker)=>Number.isInteger(m.attempt?.id)&&typeof m.attempt?.history_occurred_at==='string'&&typeof m.label==='string'&&typeof m.identityKey==='string')) { setMarkers(saved.markers);if(saved.browsePage)setBrowsePage(saved.browsePage);identitySerial.current=saved.serial??16 }
    } catch { /* A corrupt or unavailable local draft must not stop navigation. */ }
    setDraftReady(true)
    if(!startInSessions || initialEpisode) void load(initialEpisode?.anchor_id ?? 0, true, !initialEpisode?.anchor_id ? initialEpisode?.start_at ?? '' : '', initialEpisode?.anchor_id ? 'around' : 'after', initialEpisode?.anchor_id ?? undefined)
    void loadIdentities()
    return () => { alive.current = false; epoch.current++; controller.current?.abort() }
    // This component is keyed by diver, track and exact context in its parent.
  }, [])
  useEffect(()=>{
    if(!draftReady)return
    try { if(markers.length)localStorage.setItem(storageKey,JSON.stringify({markers,browsePage,serial:identitySerial.current}));else localStorage.removeItem(storageKey) } catch { /* Saving to the server remains available. */ }
  },[markers,browsePage,draftReady,storageKey])
  useEffect(() => {
    const index = items.findIndex(a => a.id === current?.id)
    if (sessionsOpen || loading || review || error || editing) return
    if (index >= items.length - 6 && next != null) void load(next)
    else if (index >= 0 && index <= 5 && previous != null) void load(items[0].id, false, appliedSeek.current, 'before')
  }, [current?.id, next, previous, loading, review, error, editing])

  function quit() {
    if (saving) return
    if (editing && label.trim() && !window.confirm(t('technique.discardName'))) return
    onClose()
  }
  async function chooseSession(session:TechniqueSession,exact:boolean,approximate=false) {
    setSessionsOpen(false);setReview(false);setActiveSession(session.session_id);setReturnToSessions(!exact)
    setUncertainUntil(approximate ? new Date(Date.parse(session.last_at+'Z')+1000).toISOString().replace(/Z$/,'') : undefined)
    await loadSessionStart(session,!exact)
  }
  async function loadSessionStart(session:TechniqueSession,nameNow:boolean) {
    const generation=++epoch.current;controller.current?.abort();setLoading(true);setError('');setCurrent(null)
    const abort=new AbortController();controller.current=abort
    try {
      const {data}=await api.post(`${base}/attempts`,{...context,session_id:session.session_id,after:0},{signal:abort.signal})
      if(!alive.current||epoch.current!==generation)return
      if(data.revision!==version.current){setErrorKind('revision');setError(t('technique.conflict'));return}
      const first=data.items[0]
      setItems(data.items);setNext(data.next);setPrevious(null);setCurrent(first??null)
      if(first&&nameNow&&(independent||!(first.intended_scope===context.code&&first.intended_start_id===first.id&&first.episode_id))){editingDraftKey.current=null;setReplacementChoice(null);setReplacement('');setEditing(first);setLabel(nameDraft);setSelectedIdentity('new')}
    } catch { if(alive.current&&!abort.signal.aborted&&epoch.current===generation)setError(t('technique.unavailable')) }
    finally {if(alive.current&&epoch.current===generation)setLoading(false)}
  }
  function openReview() {
    setReview(true);setSessionsOpen(false);setReviewed(false);void reviewOrSave(false)
  }
  function beginMarker(forceNew = false) {
    if (!current || saving) return
    setReturnToSessions(false);setUncertainUntil(undefined)
    const marker = forceNew ? undefined : markers.find(m => m.attempt.id === current.id)
    editingDraftKey.current=marker?markerKey(marker):null;setReplacementChoice(marker?.replaceEpisode?{id:marker.replaceEpisode,label:marker.replaceLabel??null}:null);setReplacement(marker?.replaceEpisode?`episode:${marker.replaceEpisode}`:marker?.replaceDraft?`draft:${marker.replaceDraft}`:'')
    setSelectedIdentity(marker?.techniqueId ? `id:${marker.techniqueId}` : marker?.identityKey ?? 'new'); setLabel(marker?.label ?? nameDraft); setEditing(current); setReviewed(false)
  }
  function keepMarker() {
    if (!editing || !label.trim()) return
    const normalized=label.trim().toLocaleLowerCase()
    const exact=identities.filter(item=>item.label.trim().toLocaleLowerCase()===normalized)
    const known = selectedIdentity.startsWith('id:') ? { id: Number(selectedIdentity.slice(3)), label } : exact.length===1 ? exact[0] : null
    const reused = markers.find(item => item.identityKey === selectedIdentity) ?? markers.find(item=>item.label.trim().toLocaleLowerCase()===normalized)
    const identityKey = known ? `id:${known.id}` : reused?.identityKey ?? `new:${++identitySerial.current}`
    setMarkers(previous => [...previous.filter(m => independent ? markerKey(m)!==editingDraftKey.current : m.attempt.id !== editing.id), { attempt: editing, label: known?.label ?? reused?.label ?? label.trim(), saved: false, identityKey, techniqueId: known?.id ?? reused?.techniqueId,uncertainUntil,sessionStart:returnToSessions,replaceEpisode:replacement.startsWith('episode:')?Number(replacement.slice(8)):undefined,replaceDraft:replacement.startsWith('draft:')?replacement.slice(6):undefined,replaceLabel:replacementChoice?.label??undefined }])
    setEditing(null); setLabel(''); setNameDraft(''); setReviewed(false);setUncertainUntil(undefined);if(returnToSessions)setSessionsOpen(true)
  }
  async function reviewOrSave(save = false) {
    if (saving || !pending.length) return
    setSaving(true); setError(''); setErrorKind(null)
    try {
      if (!save) {
        const { data } = await api.post(independent?`${independent.base}/preview`:`${base}/setup-preview`, { ...(independent?{revision:independentVersion.current}:{}),changes: pending.map(marker => change(marker, version.current)) })
        if (!alive.current) return
        setImpacts(data.items); setReviewed(true)
      } else {
        const { data } = await api.post(independent?`${independent.base}/save`:`${base}/setup-save`, { ...(independent?{revision:independentVersion.current}:{}),changes: pending.map(marker => change(marker, version.current)) })
        if (!alive.current) return
        version.current = data.revision
        try { localStorage.removeItem(storageKey) } catch {}
        onDone()
      }
    } catch (failure) { if (alive.current) { const detail = (failure as { response?: { data?: { detail?: { marker_index?: number; reason?: string } | string } } }).response?.data?.detail; const issue = typeof detail === 'object' ? detail : null; const marker = issue?.marker_index != null ? pending[issue.marker_index] : null; const conflict = typeof detail === 'string' && detail.startsWith('History changed'); const status = (failure as { response?: { status?: number } }).response?.status; setErrorKind(conflict ? 'revision' : save && (!status || status >= 500) ? 'retry' : 'validation'); setError(conflict ? t('technique.conflict') : save ? t('technique.setupSaveError') : t(issue?.reason === 'Boundary already exists' ? 'technique.boundaryExists' : 'technique.setupPreviewError', { name: marker?.label ?? pending[0]?.label })); setReviewed(false) } }
    finally { if (alive.current) setSaving(false) }
  }
  async function adjustBoundary(episodeId = current?.episode_id) {
    if (!episodeId || !onAdjust || saving) return
    if (pending.length && !window.confirm(t('technique.switchToAdjustment'))) return
    setSaving(true)
    try {
      const { data } = await api.get(`${base}/episodes/${episodeId}`)
      if (!alive.current) return
      if (data.revision !== version.current) { setErrorKind('revision'); setError(t('technique.conflict')); return }
      onAdjust(data.episode)
    } catch { if (alive.current) setError(t('technique.unavailable')) }
    finally { if (alive.current) setSaving(false) }
  }
  function asAttempt(row: HistoryAttempt): Attempt {
    return { ...row, performance_numeric: ({ F: 0, B: 1, M: 2, G: 3, P: 4 } as Record<string, number>)[row.performance] ?? 0, height: context.height, platform_type: context.apparatus, position: context.position, is_sync: context.sync, is_lineup: false, official_dd: null }
  }
  const moving = markers.find(marker => marker.identityKey + ':' + marker.attempt.id === movingKey)
  const proposed = draft.filter(marker => current && (Boolean(initialEpisode && current.episode_id === initialEpisode.id) || !current.intended_start_at || marker.attempt.history_occurred_at > current.intended_start_at || (marker.attempt.history_occurred_at === current.intended_start_at && marker.attempt.id >= (current.intended_start_id ?? 0))) && (marker.attempt.history_occurred_at < current.history_occurred_at || (marker.attempt.history_occurred_at === current.history_occurred_at && marker.attempt.id <= current.id))).slice(-1)[0]
  const draftChoices = [...new Map(markers.filter(marker => !marker.techniqueId).map(marker => [marker.identityKey, marker])).values()]
  const boundaryHere = !independent && current?.intended_scope === context.code && current?.intended_start_id === current?.id && current?.episode_id != null
  const markerHere = markers.find(m => m.attempt.id === current?.id)
  const ordinal=(a:HistoryAttempt)=>t('technique.sessionAttempt',{index:a.session_index??1,total:a.session_total??1})
  useEffect(()=>{if(!editing)return;let inner=0;const frame=requestAnimationFrame(()=>{inner=requestAnimationFrame(()=>document.querySelector<HTMLInputElement>('input[name=technique-change-label]')?.focus())});return()=>{cancelAnimationFrame(frame);cancelAnimationFrame(inner)}},[editing?.id])
  const content = <>
    {removedMarker&&<div role="status" className="th-notice"><button className="th-text-button" onClick={()=>{setMarkers(p=>[...p,removedMarker]);setRemovedMarker(null);setReviewed(false)}}>{t('technique.undoRemove')}</button></div>}
    {error && <div><p className="th-error" role="alert">{error}</p>{(errorKind === 'revision' || errorKind === 'retry') && <button className="th-text-button" disabled={saving || loading} onClick={async () => {
      const generation = epoch.current
      try { const { data } = await api.get(`${base}/revisions`); if (alive.current && generation === epoch.current) { version.current = data.revision; setReviewed(false); setError(''); if(independent){const result=await api.post(`${independent.base}/list`,context);if(alive.current)independentVersion.current=result.data.revision} if (!review) void load(next ?? 0, !current) } }
      catch { if (alive.current && generation === epoch.current) setError(t('technique.unavailable')) }
    }}>{t('technique.recheckHistory')}</button>}</div>}
    {review ? <div className="th-setup-review-body">
      <h3 className="th-setup-review-title">{t('technique.setupReview')}</h3>
      <p className="th-setup-help">{trackName&&`${trackName} · `}{context.code} · {t(context.apparatus==='platform'?'technique.platform':'technique.springboard')} · {context.height} · {initialEpisode && initialEpisode.position == null ? t('technique.allPositions') : context.position} · {t(initialEpisode && initialEpisode.sync == null ? 'technique.individualAndSync' : context.sync ? 'technique.onlySync' : 'technique.onlyIndividual')}</p>
      <ol className="th-setup-review-list">{draft.map(marker => { const impact = reviewed ? impacts.find(item => independent ? item.draft_key===markerKey(marker) : item.anchor_id === marker.attempt.id) : null; return <li key={markerKey(marker)}>
        <div><button className="th-text-button" disabled={saving} onClick={() => { setReview(false); setReviewed(false); setSeek(''); void load(marker.attempt.id, true, '', 'around', marker.attempt.id) }}><strong>{marker.label}</strong></button><strong>{marker.saved && <Check size={14} aria-label={t('technique.saved')} />}</strong><small>{marker.uncertainUntil ? '≈ ' : ''}{date(marker.attempt.history_occurred_at)} · {t('technique.sessionAttempt',{index:marker.attempt.session_index??1,total:marker.attempt.session_total??1})}{impact ? ` – ${impact.end_at ? date(impact.end_at) : t('technique.now')}` : ''}</small></div>
        {!marker.saved && <div><button className="th-icon" disabled={saving} aria-label={t('technique.edit')} onClick={() => { if (!items.some(a => a.id === marker.attempt.id)) { setSeek(''); void load(marker.attempt.id, true, '', 'around', marker.attempt.id) } else setCurrent(marker.attempt); editingDraftKey.current=markerKey(marker);setReplacementChoice(marker.replaceEpisode?{id:marker.replaceEpisode,label:marker.replaceLabel??null}:null);setReplacement(marker.replaceEpisode?`episode:${marker.replaceEpisode}`:marker.replaceDraft?`draft:${marker.replaceDraft}`:'');setEditing(marker.attempt); setSelectedIdentity(marker.techniqueId ? `id:${marker.techniqueId}` : marker.identityKey); setLabel(marker.label); setReview(false); setReviewed(false) }}><Pencil size={15} /></button><button className="th-icon" disabled={saving} aria-label={t('technique.moveBoundary')} onClick={() => {
          setMovingKey(marker.identityKey + ':' + marker.attempt.id); setReview(false); setReviewed(false); setSeek(''); void load(marker.attempt.id,true,'','around',marker.attempt.id)
        }}><Flag size={15} /></button><button className="th-icon" disabled={saving} aria-label={t('technique.removeMarker')} onClick={() => { setRemovedMarker(marker);setMarkers(p => p.filter(m => markerKey(m)!==markerKey(marker))); setReviewed(false) }}><Trash2 size={15} /></button></div>}
        {impact && <div className="th-setup-impact">{independent&&!impact.replaces&&!initialEpisode&&<small>{t('adjustments.adds')}</small>}<small>{techniqueImpact(t, impact.counts.affected, impact.counts.explicit_preserved)}</small>{impact.same_previous&&<small>{t('technique.samePrevious')}</small>}{impact.same_following&&<small>{t('technique.sameFollowing')}{impact.following&&onAdjust&&<button className="th-text-button" disabled={saving} onClick={()=>void adjustBoundary(impact.following!.id)}>{t('technique.adjustFollowing')}</button>}</small>}{independent&&!impact.end_at&&<small>{t('adjustments.continues')}</small>}{impact.next_label&&<small>{t('technique.endsAtNext',{name:impact.next_label})}</small>}{impact.replaces && <small>{t('technique.replacesPeriod', { name: impact.replaces })}</small>}{impact.following && <small>{t('technique.existingContinues', { name: impact.following.label ?? t('technique.unknown'), date: date(impact.following.start_at) })}</small>}</div>}
      </li>})}</ol>
      <div className="th-dialog-actions th-setup-footer"><button className="th-secondary" disabled={saving} onClick={() => { setReview(false); setReviewed(false);setSessionsOpen(startInSessions&&!initialEpisode) }}>{t('technique.keepBrowsing')}</button><button className="th-primary" disabled={saving || !pending.length} onClick={() => void reviewOrSave(reviewed)}>{t(saving ? (reviewed ? 'technique.setupSaving' : 'technique.checkingChanges') : reviewed ? 'technique.saveChanges' : 'technique.reviewChange')}</button></div>
    </div> : editing ? <form className="th-setup-edit" onSubmit={e => { e.preventDefault(); keepMarker() }}>
      <label className="th-field">{t(independent?'adjustments.whatChanges':'technique.whichTechnique')}<input list="technique-known-names" autoFocus autoComplete="off" name="technique-change-label" maxLength={120} required value={label} placeholder={t('technique.labelExample')} onChange={e=>{setLabel(e.target.value);setSelectedIdentity('new')}} /></label>
      <datalist id="technique-known-names">{[...new Set([...(independent?independent.choices.map(item=>item.label??''):identities.map(item=>item.label)),...draftChoices.map(item=>item.label)])].map(name=><option key={name} value={name}/>)}</datalist>
      {!independent&&([...identities,...draftChoices].some(item=>item.label.trim().toLocaleLowerCase()===label.trim().toLocaleLowerCase()))&&<p className="th-notice">{t('technique.reusingTechnique',{name:label.trim()})}</p>}
      {!independent&&identityNext!=null&&<button type="button" className="th-text-button" onClick={()=>void loadIdentities(identityNext)}>{t('technique.moreTechniques')}</button>}
      {independent&&!initialEpisode&&<label className="th-field">{t('adjustments.behavior')}<select value={replacement} onChange={e=>{setReplacement(e.target.value);setReplacementChoice(independent.choices.find(item=>`episode:${item.id}`===e.target.value)??null)}}><option value="">{t('adjustments.adds')}</option>{replacementChoice&&!independent.choices.some(item=>item.id===replacementChoice.id)&&<option value={`episode:${replacementChoice.id}`}>{t('adjustments.replaces',{name:replacementChoice.label})}</option>}{independent.choices.filter(e=>e.anchor_id!==editing.id&&e.start_at<=editing.history_occurred_at&&(!e.end_at||editing.history_occurred_at<=e.end_at)).map(e=><option key={e.id} value={`episode:${e.id}`}>{t('adjustments.replaces',{name:e.label})}</option>)}{draft.filter(m=>markerKey(m)!==editingDraftKey.current&&(m.attempt.history_occurred_at<editing.history_occurred_at||m.attempt.history_occurred_at===editing.history_occurred_at&&m.attempt.id<editing.id)).map(m=><option key={markerKey(m)} value={`draft:${markerKey(m)}`}>{t('adjustments.replaces',{name:m.label})}</option>)}</select>{independent.more&&<button className="th-text-button" type="button" onClick={independent.onMore}>{t('adjustments.more')}</button>}</label>}
      <p className="th-setup-help">{uncertainUntil?'≈ ':''}{t('technique.startsAtClip', { date: date(editing.history_occurred_at) })} · {ordinal(editing)}{uncertainUntil&&<span> · {t('technique.uncertainSession')}</span>}</p>
      <div className="th-dialog-actions"><button type="button" className="th-secondary" onClick={() => {setNameDraft(label);setEditing(null);if(returnToSessions)setSessionsOpen(true)}}>{t('technique.cancel')}</button><button className="th-primary">{t(returnToSessions?'technique.addChange':'technique.keepMarker')}</button></div>
    </form> : <>
      <details className="th-setup-context"><summary>{independent?t('adjustments.context'):current?.intended_label ?? t('technique.unrecorded')} · {context.code} · {context.height}</summary><div className="th-setup-position"><strong>{current ? date(current.dive_datetime) : context.code}</strong><span>{trackName&&`${trackName} · `}{context.code} · {t(context.apparatus==='platform'?'technique.platform':'technique.springboard')} · {context.height} · {initialEpisode && initialEpisode.position == null ? t('technique.allPositions') : context.position} · {t(initialEpisode && initialEpisode.sync == null ? 'technique.individualAndSync' : context.sync ? 'technique.onlySync' : 'technique.onlyIndividual')}</span></div>
      {!independent&&<p className="th-setup-help">{t('technique.currentTechnique', { name: current?.intended_label ?? t('technique.unrecorded') })}</p>}
      {!independent && proposed && proposed.label !== current?.intended_label && <p className="th-setup-help">{t('technique.proposedTechnique', { name: proposed.label })}</p>}</details>

      {moving && <div className="th-setup-edit"><strong>{t('technique.movingBoundary', { name: moving.label })}</strong><button className="th-primary" disabled={!independent&&Boolean(markerHere && markerHere !== moving)} onClick={() => {
        if (!current) return
        setMarkers(previous => previous.map(marker => marker === moving ? { ...marker, attempt: current } : marker))
        setMovingKey(null); setReviewed(false)
      }}>{t('technique.moveStartHere')}</button><button className="th-text-button" onClick={() => setMovingKey(null)}>{t('technique.cancel')}</button></div>}
      {!moving && boundaryHere && !markerHere && onAdjust ? <button className="th-primary" onClick={() => void adjustBoundary()}>{t('technique.adjustExisting')}</button> : !moving && <div className="th-setup-controls"><button className="th-primary" disabled={!current || saving || (!markerHere && (markers.length >= 16 || Boolean(initialEpisode))) || markerHere?.saved} onClick={()=>beginMarker()}><Flag size={16} />{t(markerHere ? 'technique.editMarker' : independent?'adjustments.markHere':'technique.markStart')}</button></div>}
      {independent&&markerHere&&!initialEpisode&&<button className="th-text-button" onClick={()=>beginMarker(true)}>{t('adjustments.anotherHere')}</button>}
      {markerHere && <p className="th-notice" role="status"><Check size={14} />{markerHere.label}</p>}

      <div className="th-setup-navigation"><button className="th-text-button" onClick={()=>{setSessionsOpen(true);setEditing(null)}}>{t('technique.chooseAnotherSession')}</button><button className="th-text-button" disabled={!markers.length} onClick={() => { setReview(true); setReviewed(false); void reviewOrSave(false) }}>{t('technique.reviewMarkers', { count: markers.length })}</button>{!activeSession&&<button className="th-text-button" onClick={() => setShowSeek(v => !v)}>{t('technique.jumpDate')}</button>}</div>
      {showSeek && <form className="th-inline-form" onSubmit={e => { e.preventDefault(); setEditing(null); void load(0,true,seek) }}><label className="th-field">{t('technique.from')}<input type="date" value={seek} onChange={e => setSeek(e.target.value)} /></label><button className="th-secondary">{t('technique.go')}</button></form>}
      {loading && <p className="th-setup-help" role="status">{t('technique.loadingClips')}</p>}
      {!activeSession && !loading && next == null && <button className="th-text-button" onClick={() => { setSeek(''); void load(0,true,'') }}>{t('technique.backToFirstClip')}</button>}
      {markers.length >= 16 && <p className="th-setup-help">{t('technique.markerLimit')}</p>}
    </>}
  </>
  if(sessionsOpen) return <TechniqueDialog title={t('technique.fillHistory')} onClose={quit}><TechniqueSessionBrowser hideTechnique={Boolean(independent)} exactOnly={Boolean(initialEpisode)} initialPage={browsePage} onPageChange={setBrowsePage} onRevision={rev=>{version.current=rev;setReviewed(false)}} base={base} context={context} revision={version.current} count={markers.length} onChoose={(session,exact,approximate)=>void chooseSession(session,exact,approximate)} onReview={openReview}/>{markers.length>0&&<div className="th-draft-summary"><h3>{t('technique.reviewMarkers',{count:markers.length})}</h3>{draft.map(marker=><p key={markerKey(marker)}><strong>{marker.label}</strong> · {marker.uncertainUntil?'≈ ':''}{date(marker.attempt.history_occurred_at)} · {ordinal(marker.attempt)}</p>)}<p>{t('technique.draftKept')}</p></div>}</TechniqueDialog>
  if (!current) return <TechniqueDialog title={t('technique.setupTitle')} onClose={quit}><div className="th-form">
    {review ? content : error ? <div><p className="th-error" role="alert">{error}</p>{authError && <a className="th-secondary" href="/login" target="_blank" rel="noreferrer">{t('technique.signInAgain')}</a>}<button className="th-secondary" onClick={async () => { try { const { data } = await api.get(`${base}/revisions`); if (!alive.current) return; version.current = data.revision; void load(0,true) } catch { if (alive.current) setError(t('technique.unavailable')) } }}>{t('technique.recheckHistory')}</button></div>
    : loading ? <p role="status">{t('technique.loadingClips')}</p>
    : <><p>{t('technique.noClips')}</p><button className="th-secondary" onClick={() => { setSeek(''); void load(0,true,'') }}>{t('technique.backToFirstClip')}</button></>}
  </div></TechniqueDialog>
  return <ClipViewer attempt={asAttempt(current)} attempts={items.map(asAttempt)} onMove={a => { if (!editing && !saving) setCurrent(items.find(row => row.id === a.id) ?? current) }} onClose={quit} playbackRate={rate} onPlaybackRateChange={setRate} workflow={{ title: t('technique.setupTitle'), backLabel: context.code, content, navigationDisabled: Boolean(editing || saving), history: { sessionLabel: activeSession ? date(current.dive_datetime).split(' · ')[0] : undefined, total: activeSession ? current.session_total ?? items.length : current.history_total ?? items.length, previous: previous != null, next: next != null, loading, onPrevious: () => void load(items[0].id, false, '', 'before'), onNext: () => { if (next != null) void load(next) } }, positionLabel: current.session_index && current.session_total ? t('technique.sessionAttempt', { index: current.session_index, total: current.session_total }) : date(current.dive_datetime) }} />
}
