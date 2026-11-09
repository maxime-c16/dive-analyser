import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Flag, Pencil, Trash2 } from 'lucide-react'
import ClipViewer from '../clip-viewer/ClipViewer'
import TechniqueDialog from './TechniqueDialog'
import { techniqueDateTime } from './techniqueDates'
import { api } from '../../services/api'
import type { Attempt } from '../../utils/attemptPresentation'

type Context = { code: string; apparatus: string; height: string; position: string; sync: boolean }
type HistoryAttempt = { id: number; session_id: number; dive_code: string; dive_datetime: string; history_occurred_at: string; video_uuid?: string | null; performance: string }
type Marker = { attempt: HistoryAttempt; label: string; saved: boolean; impact?: number }
const ordered = (markers: Marker[]) => [...markers].sort((a, b) => a.attempt.history_occurred_at.localeCompare(b.attempt.history_occurred_at) || a.attempt.id - b.attempt.id)

/** Reuses the Library's player/gesture owner. Only a 100-clip navigation window
 * and at most 16 pending boundaries are retained; dates can seek the full history. */
export default function TechniqueSetup({ base, context, revision, constrainPosition, constrainSync, onClose, onDone }: {
  base: string; context: Context; revision: number; constrainPosition: boolean; constrainSync: boolean; onClose: () => void; onDone: () => void
}) {
  const { t, i18n } = useTranslation()
  const [items, setItems] = useState<HistoryAttempt[]>([])
  const [current, setCurrent] = useState<HistoryAttempt | null>(null)
  const [next, setNext] = useState<number | null>(null)
  const [previous, setPrevious] = useState<number | null>(null)
  const [loading, setLoading] = useState(true), [error, setError] = useState('')
  const [seek, setSeek] = useState(''), [showSeek, setShowSeek] = useState(false)
  const [rate, setRate] = useState(1)
  const [markers, setMarkers] = useState<Marker[]>([])
  const [editing, setEditing] = useState<HistoryAttempt | null>(null), [label, setLabel] = useState('')
  const [review, setReview] = useState(false), [saving, setSaving] = useState(false)
  const [reviewed, setReviewed] = useState(false)
  const [savedCount, setSavedCount] = useState(0)
  const appliedSeek = useRef('')
  const version = useRef(revision), alive = useRef(true), epoch = useRef(0), fetching = useRef(false)
  const controller = useRef<AbortController | null>(null)
  const date = (value: string) => techniqueDateTime(value, i18n.language)
  const draft = ordered(markers)
  const pending = draft.filter(m => !m.saved)
  const change = (marker: Marker, rev: number) => ({ ...context, revision: rev, label: marker.label, scope: context.code, anchor_id: marker.attempt.id, start_at: marker.attempt.history_occurred_at, precision: 'attempt', timezone: 'UTC', constrain_position: constrainPosition, constrain_sync: constrainSync })

  async function load(after: number, replace = false, from = appliedSeek.current, direction: 'after' | 'before' | 'around' = 'after', focusId?: number) {
    if (fetching.current && !replace) return
    if (replace) { controller.current?.abort(); epoch.current++; appliedSeek.current = from; setCurrent(null) }
    const generation = epoch.current
    const abort = new AbortController(); controller.current = abort
    fetching.current = true; setLoading(true); setError('')
    try {
      const { data } = await api.post(`${base}/attempts`, { ...context, after: direction === 'after' ? after : 0, before: direction === 'before' ? after : 0, around: direction === 'around' ? after : 0, from_date: from ? `${from}T00:00:00` : null }, { signal: abort.signal })
      if (!alive.current || generation !== epoch.current) return
      if (data.revision !== version.current) { setError(t('technique.conflict')); return }
      const rows: HistoryAttempt[] = data.items
      if (focusId && !rows.some(row => row.id === focusId)) { setError(t('technique.anchorUnavailable')); return }
      setItems(existing => {
        if (replace) return rows
        const unique = [...new Map((direction === 'before' ? [...rows, ...existing] : [...existing, ...rows]).map(row => [row.id, row])).values()]
        const retained = direction === 'before' ? unique.slice(0,100) : unique.slice(-100)
        if (unique.length > 100) {
          if (direction === 'before') setNext(retained[retained.length - 1].id)
          else setPrevious(retained[0].id)
        }
        return retained
      })
      if (replace) { setCurrent(rows.find(row => row.id === focusId) ?? rows[0] ?? null); setPrevious(data.previous ?? null); setNext(data.next) }
      else if (direction === 'before') setPrevious(data.previous ?? null)
      else setNext(data.next)
    } catch { if (alive.current && generation === epoch.current && !abort.signal.aborted) setError(t('technique.unavailable')) }
    finally { if (alive.current && generation === epoch.current) { fetching.current = false; setLoading(false) } }
  }
  useEffect(() => {
    alive.current = true; void load(0, true, '')
    return () => { alive.current = false; epoch.current++; controller.current?.abort() }
    // This component is keyed by diver, track and exact context in its parent.
  }, [])
  useEffect(() => {
    const index = items.findIndex(a => a.id === current?.id)
    if (loading || review || error || editing) return
    if (index >= items.length - 6 && next != null) void load(next)
    else if (index >= 0 && index <= 5 && previous != null) void load(items[0].id, false, appliedSeek.current, 'before')
  }, [current?.id, next, previous, loading, review, error, editing])

  function quit() {
    if (saving) return
    if (pending.length && !window.confirm(t('technique.setupDiscard'))) return
    if (savedCount) onDone(); else onClose()
  }
  function beginMarker() {
    if (!current || saving) return
    const marker = markers.find(m => m.attempt.id === current.id)
    setLabel(marker?.label ?? ''); setEditing(current); setReviewed(false)
  }
  function keepMarker() {
    if (!editing || !label.trim()) return
    setMarkers(previous => [...previous.filter(m => m.attempt.id !== editing.id), { attempt: editing, label: label.trim(), saved: false }])
    setEditing(null); setLabel(''); setReviewed(false)
  }
  async function reviewOrSave(save = false) {
    if (saving || !pending.length) return
    setSaving(true); setError('')
    try {
      if (!save) {
        const impacts = new Map<number, number>()
        for (const marker of pending) {
          const { data } = await api.post(`${base}/preview`, change(marker, version.current))
          if (!alive.current) return
          impacts.set(marker.attempt.id, data.counts?.affected ?? 0)
        }
        setMarkers(previous => previous.map(m => ({ ...m, impact: impacts.get(m.attempt.id) ?? m.impact })))
        setReviewed(true)
      } else {
        // Each boundary has its own revisioned atomic write. On any failure,
        // saved boundaries are identified and the remaining draft stays editable.
        for (const marker of pending) {
          const { data: preview } = await api.post(`${base}/preview`, change(marker, version.current))
          if (!alive.current) return
          const { data } = await api.post(`${base}/changes`, preview.change)
          if (!alive.current) return
          version.current = data.revision
          setSavedCount(n => n + 1)
          setMarkers(previous => previous.map(m => m.attempt.id === marker.attempt.id ? { ...m, saved: true } : m))
        }
        onDone()
      }
    } catch { if (alive.current) { setError(t('technique.setupSaveError')); setReviewed(false) } }
    finally { if (alive.current) setSaving(false) }
  }
  function asAttempt(row: HistoryAttempt): Attempt {
    return { ...row, performance_numeric: ({ F: 0, B: 1, M: 2, G: 3, P: 4 } as Record<string, number>)[row.performance] ?? 0, height: context.height, platform_type: context.apparatus, position: context.position, is_sync: context.sync, is_lineup: false, official_dd: null }
  }
  const markerHere = markers.find(m => m.attempt.id === current?.id)
  const content = <>
    {error && <div><p className="th-error" role="alert">{error}</p><button className="th-text-button" disabled={saving || loading} onClick={async () => {
      const generation = epoch.current
      try { const { data } = await api.get(`${base}/revisions`); if (alive.current && generation === epoch.current) { version.current = data.revision; setReviewed(false); setError(''); if (!review) void load(next ?? 0, !current) } }
      catch { if (alive.current && generation === epoch.current) setError(t('technique.unavailable')) }
    }}>{t('technique.recheckHistory')}</button></div>}
    {review ? <div className="th-setup-review-body">
      <h3 className="th-setup-review-title">{t('technique.setupReview')}</h3>
      <p className="th-setup-help">{t('technique.setupReviewHint')}</p>
      <ol className="th-setup-review-list">{draft.map((marker, index) => <li key={marker.attempt.id}>
        <div><button className="th-text-button" disabled={saving} onClick={() => { setReview(false); setReviewed(false); setSeek(''); void load(marker.attempt.id, true, '', 'around', marker.attempt.id) }}><strong>{marker.label}</strong></button><strong>{marker.saved && <Check size={14} aria-label={t('technique.saved')} />}</strong><small>{date(marker.attempt.history_occurred_at)}{draft[index + 1] ? ` – ${date(draft[index + 1].attempt.history_occurred_at)}` : ''}</small>{marker.impact != null && !marker.saved && <small>{t('technique.setupImpact', { count: marker.impact })}</small>}</div>
        {!marker.saved && <div><button className="th-icon" disabled={saving} aria-label={t('technique.edit')} onClick={() => { if (!items.some(a => a.id === marker.attempt.id)) { setSeek(''); void load(marker.attempt.id, true, '', 'around', marker.attempt.id) } else setCurrent(marker.attempt); setEditing(marker.attempt); setLabel(marker.label); setReview(false); setReviewed(false) }}><Pencil size={15} /></button><button className="th-icon" disabled={saving} aria-label={t('technique.removeMarker')} onClick={() => { setMarkers(p => p.filter(m => m.attempt.id !== marker.attempt.id)); setReviewed(false) }}><Trash2 size={15} /></button></div>}
      </li>)}</ol>
      {savedCount > 0 && <p className="th-setup-saving" role="status">{t('technique.setupSavedCount', { count: savedCount })}</p>}
      <div className="th-dialog-actions"><button className="th-secondary" disabled={saving} onClick={() => { setReview(false); setReviewed(false) }}>{t('technique.keepBrowsing')}</button><button className="th-primary" disabled={saving || !pending.length} onClick={() => void reviewOrSave(reviewed)}>{t(saving ? (reviewed ? 'technique.setupSaving' : 'technique.checkingChanges') : reviewed ? 'technique.saveChanges' : 'technique.reviewChange')}</button></div>
    </div> : editing ? <form className="th-setup-edit" onSubmit={e => { e.preventDefault(); keepMarker() }}>
      <label className="th-field">{t('technique.whatChanged')}<input autoFocus autoComplete="off" name="technique-change-label" maxLength={120} required value={label} placeholder={t('technique.labelExample')} onChange={e => setLabel(e.target.value)} /></label>
      <p className="th-setup-help">{t('technique.startsAtClip', { date: date(editing.history_occurred_at) })}</p>
      <div className="th-dialog-actions"><button type="button" className="th-secondary" onClick={() => setEditing(null)}>{t('technique.cancel')}</button><button className="th-primary">{t('technique.keepMarker')}</button></div>
    </form> : <>
      <div className="th-setup-position"><strong>{current ? date(current.dive_datetime) : context.code}</strong><span>{context.code} · {context.height}</span></div>
      <p className="th-setup-help">{t('technique.setupBrowseHint')}</p>
      <div className="th-setup-controls"><button className="th-primary" disabled={!current || saving || (!markerHere && markers.length >= 16) || markerHere?.saved} onClick={beginMarker}><Flag size={16} />{t(markerHere ? 'technique.editMarker' : 'technique.markStart')}</button></div>
      {markerHere && <p className="th-notice"><Check size={14} />{markerHere.label}</p>}
      <div className="th-setup-navigation"><button className="th-text-button" disabled={!markers.length} onClick={() => { setReview(true); setReviewed(false); void reviewOrSave(false) }}>{t('technique.reviewMarkers', { count: markers.length })}</button><button className="th-text-button" onClick={() => setShowSeek(v => !v)}>{t('technique.jumpDate')}</button></div>
      {showSeek && <form className="th-inline-form" onSubmit={e => { e.preventDefault(); setEditing(null); void load(0,true,seek) }}><label className="th-field">{t('technique.from')}<input type="date" value={seek} onChange={e => setSeek(e.target.value)} /></label><button className="th-secondary">{t('technique.go')}</button></form>}
      {loading && <p className="th-setup-help" role="status">{t('technique.loadingClips')}</p>}
      {!loading && next == null && <button className="th-text-button" onClick={() => { setSeek(''); void load(0,true,'') }}>{t('technique.backToFirstClip')}</button>}
      {markers.length >= 16 && <p className="th-setup-help">{t('technique.markerLimit')}</p>}
    </>}
  </>
  if (!current) return <TechniqueDialog title={t('technique.setupTitle')} onClose={quit}><div className="th-form">{content}{!loading && <p>{t('technique.noClips')}</p>}<button className="th-secondary" onClick={() => { setSeek(''); void load(0,true,'') }}>{t('technique.backToFirstClip')}</button></div></TechniqueDialog>
  return <ClipViewer attempt={asAttempt(current)} attempts={items.map(asAttempt)} onMove={a => { if (!editing && !saving) setCurrent(items.find(row => row.id === a.id) ?? current) }} onClose={quit} playbackRate={rate} onPlaybackRateChange={setRate} workflow={{ title: t('technique.setupTitle'), backLabel: context.code, content }} />
}
