import SeriesComparison from '../components/series/SeriesComparison'
import SeriesCard from '../components/series/SeriesCard'
import { useSeriesReorderMotion } from '../components/series/useSeriesReorderMotion'
import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../contexts/AuthContext'
import { calendarApi } from '../calendar/api'
import { searchMembers, type MemberSummary } from '../services/communityApi'
import { seriesClipScore, seriesApi, type SeriesSheet, type SeriesSlot, type SeriesClip, type SeriesChoice } from '../services/seriesApi'
import MediaThumbnail from '../components/MediaThumbnail'
import SeriesPanel, { useSeriesMobileLayout } from '../components/series/SeriesPanel'
import SeriesPlayer, { type SeriesPlaybackEntry } from '../components/series/SeriesPlayer'
import { diveCodeName } from '../i18n/diveNames'
import { api } from '../services/api'
import './series.css'

const heights = ['1m', '3m', '5m', '7.5m', '10m']
const blank = (): SeriesSlot => ({ code: '', clip_id: null, alternatives: [] })
const sixSlots = () => Array.from({ length: 6 }, blank)
const isCode = (code: string) =>
  /^(?:[1-4][01](?:[0-9]|11)|5[1-4][0-9]{2}|6[1-3][0-9]{1,2})[ABCD]$/.test(code.trim().toUpperCase())
const cleanCode = (code: string) => code.toUpperCase().replace(/\s/g, '')
function prepareSheet(sheet: SeriesSheet): SeriesSheet {
  // Preserve five-dive sheets and all existing content; pad early drafts only.
  if (sheet.can_edit && sheet.slots.length < 5) {
    return { ...sheet, slots: [...sheet.slots, ...Array.from({ length: 6 - sheet.slots.length }, blank)] }
  }
  return sheet
}
type Panel = number | 'sharing' | null

export default function SeriesPage() {
  const { user } = useAuth()
  return <SeriesWorkspace key={user?.user_id} />
}

function SeriesWorkspace() {
  const { i18n } = useTranslation()
  const mobile = useSeriesMobileLayout()
  const fr = i18n.language.startsWith('fr')
  const text = (a: string, b: string) => fr ? a : b
  const { seriesId } = useParams()
  const [params] = useSearchParams()
  const rawEvent = Number(params.get('event'))
  const eventId = Number.isInteger(rawEvent) && rawEvent > 0 ? rawEvent : undefined
  const navigate = useNavigate()
  const [items, setItems] = useState<SeriesSheet[]>([])
  const [sheet, setSheet] = useState<SeriesSheet | null>(null)
  const [title, setTitle] = useState('')
  const [height, setHeight] = useState('1m')
  const [eventTitle, setEventTitle] = useState('')
  const [eventReady, setEventReady] = useState(!eventId)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [revision, setRevision] = useState(0)
  const [page, setPage] = useState(0)
  const [more, setMore] = useState(false)
  const [panel, setPanel] = useState<Panel>(null)
  const [playback, setPlayback] = useState<{ entries: SeriesPlaybackEntry[]; title: string; height: string; initialIndex?: number } | null>(null)
  const [comparison, setComparison] = useState<{ index: number; alternative: number; main: SeriesChoice; candidate: SeriesChoice } | null>(null)
  const [undoComparison, setUndoComparison] = useState<{ index: number; before: SeriesSlot; after: SeriesSlot } | null>(null)
  const [memberQuery, setMemberQuery] = useState('')
  const [members, setMembers] = useState<MemberSummary[]>([])
  const [previews, setPreviews] = useState<Record<string, { poster_url?: string; playback_url?: string }>>({})
  const [picker, setPicker] = useState<{ index: number; alternative: number | null; clips: SeriesClip[] } | null>(null)
  const board = useRef<HTMLOListElement>(null)
  const animateReorder = useSeriesReorderMotion(board)
  const inputs = useRef<Array<HTMLInputElement | null>>([])
  const removedSixth = useRef<SeriesSlot | null>(null)
  const lookupCache = useRef(new Map<string, { dd?: number | null; clips: SeriesClip[] }>())
  const [lookupResults, setLookupResults] = useState<Record<string, { dd?: number | null; clips: SeriesClip[] }>>({})
  const [lookupFailed, setLookupFailed] = useState<Record<string, boolean>>({})
  const clipPolicy = sheet?.clip_policy ?? 'best'
  const lookupKey = (code: string, h: string) => `${h}:${code}:${clipPolicy}`
  // Projections live separately from the draft: late replies cannot overwrite a
  // changed/reordered card, mark it dirty, or move keyboard focus.
  const resolved = (choice: SeriesChoice): SeriesChoice => {
    if (!sheet) return choice
    const result = lookupResults[lookupKey(choice.code, sheet.height)]
    return result ? { ...choice, dd: result.dd === undefined ? choice.dd : result.dd,
      clip: choice.clip_id ? choice.clip : result.clips[0] ?? null } : choice
  }
  const videoIds = [...new Set((sheet?.slots ?? []).flatMap(s => [s, ...s.alternatives])
    .flatMap(c => resolved(c).clip?.video_uuid ? [resolved(c).clip!.video_uuid] : []))].sort().join(',')
  useEffect(() => {
    let live = true
    setPreviews({})
    if (videoIds) api.post('/api/v1/media/status/batch', { video_uuids: videoIds.split(',') })
      .then(r => { if (live) setPreviews(r.data) }).catch(() => { /* Clip links remain available. */ })
    return () => { live = false }
  }, [videoIds])
  const pendingCodes = [...new Set((sheet?.slots ?? []).flatMap(s => [s, ...s.alternatives])
    .filter(c => isCode(c.code) && c.dd === undefined).map(c => c.code))].sort().join(',')
  const lookupHeight = sheet?.height
  useEffect(() => {
    if (!pendingCodes || !lookupHeight) return
    let live = true
    const timer = window.setTimeout(() => {
      pendingCodes.split(',').forEach(async code => {
        const key = `${lookupHeight}:${code}:${clipPolicy}`
        const cached = lookupCache.current.get(key)
        if (cached) { if (live) setLookupResults(r => ({ ...r, [key]: cached })); return }
        try {
          const [dd, clips] = await Promise.all([
            api.get<{ dd_value: number }>(`/api/v1/dd/lookup/${code}/${lookupHeight}`)
              .then(r => r.data.dd_value).catch(e => {
                if (e.response?.status === 404) return null
                throw e
              }).then(dd => {
                if (live) setLookupResults(r => ({ ...r, [key]: { dd, clips: r[key]?.clips ?? [] } }))
                return dd
              }),
            seriesApi.clips(code, lookupHeight, clipPolicy).then(clips => {
              if (live) setLookupResults(r => ({ ...r, [key]: { dd: r[key]?.dd, clips } }))
              return clips
            }),
          ])
          const result = { dd, clips }
          lookupCache.current.set(key, result)
          if (live) { setLookupResults(r => ({ ...r, [key]: result })); setLookupFailed(r => ({ ...r, [key]: false })) }
        } catch { if (live) setLookupFailed(r => ({ ...r, [key]: true })) }
      })
    }, 180)
    return () => { live = false; window.clearTimeout(timer) }
  }, [pendingCodes, lookupHeight, revision, clipPolicy])

  const failure = (e: unknown) => {
    const status = (e as { response?: { status?: number } }).response?.status
    setError(status === 409 ? text('Cette série a changé dans un autre onglet. Recharge-la avant de poursuivre.', 'This series changed in another tab. Reload it before continuing.')
      : status === 404 ? text('Série ou compétition indisponible.', 'Series or competition unavailable.')
      : text('Impossible d’enregistrer ou de charger. Tes modifications restent affichées ; réessaie.', 'Could not save or load. Your changes remain on screen; try again.'))
  }
  useEffect(() => {
    let live = true
    setLoading(true); setError(''); setSheet(null); setDirty(false); setPicker(null); setPanel(null); setPlayback(null); setComparison(null); setUndoComparison(null); setNotice(''); setPage(0)
    removedSixth.current = null
    lookupCache.current.clear(); setLookupResults({}); setLookupFailed({})
    const task = seriesId ? seriesApi.get(Number(seriesId)).then(s => { if (live) setSheet(prepareSheet(s)) })
      : seriesApi.list(eventId).then(s => { if (live) { setItems(s); setMore(s.length === 50) } })
    task.catch(e => { if (live) failure(e) }).finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [seriesId, eventId, revision])
  useEffect(() => {
    let live = true
    setEventTitle(''); setEventReady(!eventId)
    if (eventId) calendarApi.event(eventId).then(e => {
      if (live && e.event_type === 'competition') { setEventTitle(e.title); setEventReady(true) }
    }).catch(e => { if (live) failure(e) })
    return () => { live = false }
  }, [eventId])
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = '' } }
    window.addEventListener('beforeunload', warn)
    const guard = (e: MouseEvent) => {
      const link = e.target instanceof Element ? e.target.closest('a[href]') : null
      if (!dirty || !link || link.getAttribute('target') === '_blank') return
      if (!window.confirm(text('Quitter sans enregistrer les modifications ?', 'Leave without saving changes?'))) {
        e.preventDefault(); e.stopPropagation()
      }
    }
    document.addEventListener('click', guard, true)
    return () => { window.removeEventListener('beforeunload', warn); document.removeEventListener('click', guard, true) }
  }, [dirty, fr])
  useEffect(() => {
    const controller = new AbortController()
    setMembers([])
    if (panel !== 'sharing' || memberQuery.trim().length < 2) return
    const timer = window.setTimeout(() => {
      searchMembers(memberQuery, undefined, controller.signal).then(r => setMembers(r.items))
        .catch(e => { if (!controller.signal.aborted) failure(e) })
    }, 250)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [memberQuery, panel])

  const mutate = (slots: SeriesSlot[]) => {
    if (!sheet || !sheet.can_edit || busy) return
    setSheet({ ...sheet, slots }); setDirty(true); setPicker(null); setNotice(''); setError('')
  }
  const change = (index: number, update: Partial<SeriesSlot>) => {
    if (sheet) mutate(sheet.slots.map((s, i) => i === index ? { ...s, ...update } : s))
  }
  const focus = (index: number) => {
    const input = inputs.current[index]
    input?.focus(); input?.select()
    input?.scrollIntoView?.({ block: 'nearest', inline: 'nearest', behavior: 'auto' })
  }
  const enterCode = (index: number, raw: string, caret: number | null) => {
    const code = cleanCode(raw)
    const previous = sheet?.slots[index].code ?? ''
    change(index, { code, clip_id: null, dd: undefined, clip: null })
    const readyToAdvance = !/^[56]/.test(code) || code.length === 5
    // Advance only when completing a code at its end. Deleting a digit can
    // leave a different valid armstand code; editing its middle must never
    // steal focus, even when the resulting code is syntactically complete.
    if (readyToAdvance && isCode(code) && code.length > previous.length && caret === raw.length) focus(index + 1)
  }
  const move = (index: number, delta: number) => {
    if (!sheet) return
    animateReorder(index, index + delta)
    const slots = [...sheet.slots]
    ;[slots[index], slots[index + delta]] = [slots[index + delta], slots[index]]
    mutate(slots)
    if (panel === index) setPanel(index + delta)
    else if (panel === index + delta) setPanel(index)
  }
  const keyInCode = (e: KeyboardEvent<HTMLInputElement>, index: number) => {
    const input = e.currentTarget
    if (e.key === 'Enter' || (e.key === 'ArrowRight' && input.selectionStart === input.value.length)) {
      e.preventDefault(); focus(index + 1)
    } else if ((e.key === 'Backspace' && !input.value) || (e.key === 'ArrowLeft' && input.selectionStart === 0)) {
      if (index > 0) { e.preventDefault(); focus(index - 1) }
    }
  }
  const save = async () => {
    if (!sheet || busy || !dirty || !sheet.can_edit) return
    if (sheet.slots.some(s => (s.code && !isCode(s.code)) || s.alternatives.some(c => c.code && !isCode(c.code)))) {
      setError(text('Complète les codes commencés, ou efface-les pour garder une place vide.', 'Complete partial codes, or clear them to leave an empty slot.')); return
    }
    setBusy(true); setError('')
    try { setSheet(prepareSheet(await seriesApi.save(sheet))); lookupCache.current.clear(); setLookupResults({}); setDirty(false); setNotice(text('Série enregistrée.', 'Series saved.')) }
    catch (e) { failure(e) } finally { setBusy(false) }
  }
  const share = async (ids: number[]) => {
    if (!sheet) return
    setBusy(true); setError('')
    try { setSheet(prepareSheet(await seriesApi.share(sheet, ids))); setMemberQuery(''); setNotice(text('Partage mis à jour.', 'Sharing updated.')) }
    catch (e) { failure(e) } finally { setBusy(false) }
  }
  const pick = async (index: number, alternative: number | null, code: string) => {
    if (!sheet || !isCode(code)) return
    setBusy(true); setError('')
    try { setPicker({ index, alternative, clips: await seriesApi.clips(code, sheet.height, clipPolicy) }) }
    catch (e) { failure(e) } finally { setBusy(false) }
  }
  const diveName = (code: string) => {
    if (!code || !isCode(code)) return ''
    const name = diveCodeName(code, fr ? 'fr' : 'en', { extended: true })
    return name === code ? text('Nom non reconnu', 'Name not recognized') : name
  }
  const codeLabel = (choice: SeriesChoice) => {
    const c = resolved(choice)
    if (!c.code) return 'DD —'
    if (!isCode(c.code)) return text('Code à compléter', 'Complete the code')
    if (c.dd != null) return `DD ${c.dd.toFixed(1)}`
    if (lookupFailed[lookupKey(c.code, sheet!.height)]) return text('DD à réessayer', 'Retry DD lookup')
    return c.dd === undefined ? text('Calcul DD…', 'Calculating DD…') : text('DD indisponible', 'DD unavailable')
  }
  const clipInfo = (choice: SeriesChoice) => {
    const c = resolved(choice)
    return c.clip ? <div className="series-clip">
      {previews[c.clip.video_uuid] && <Link to={c.clip.url} target="_blank" className="series-thumb" aria-label={text('Voir le clip', 'View clip')}><MediaThumbnail posterUrl={previews[c.clip.video_uuid].poster_url} playbackUrl={previews[c.clip.video_uuid].playback_url} /></Link>}
      <Link to={c.clip.url} target="_blank" rel="noreferrer">{text('Voir le clip', 'View clip')} · {new Date(c.clip.date + (c.clip.date.endsWith('Z') ? '' : 'Z')).toLocaleDateString(fr ? 'fr' : 'en')}</Link>
      <span>{seriesClipScore(c.clip) !== null ? `${seriesClipScore(c.clip)}/10${c.clip.rating_count ? ` · ${c.clip.rating_count} ${text('avis', 'ratings')}` : ''}` : c.clip_id ? text('Choix manuel', 'Manual selection') : text('Le plus récent', 'Most recent')}</span>
    </div> : <p className="series-muted">{text('Aucun clip associé.', 'No linked clip.')}</p>
  }
  const openPlayer = (initialIndex?: number) => {
    if (!sheet) return
    setPlayback({ entries: sheet.slots.map(s => { const clip = resolved(s).clip ?? null; const preview = clip ? previews[clip.video_uuid] : undefined; return { code: s.code, clip, poster: preview?.poster_url, playbackUrl: preview?.playback_url } }), title: sheet.title, height: sheet.height, initialIndex })
  }
  const availableClips = sheet?.slots.filter(s => resolved(s).clip).length ?? 0
  const selected = sheet && typeof panel === 'number' ? sheet.slots[panel] : null
  const filled = sheet?.slots.filter(s => isCode(s.code)).length ?? 0
  const known = sheet?.slots.map(resolved).filter(s => s.code && s.dd != null) ?? []
  const totalDD = known.reduce((sum, s) => sum + s.dd!, 0)

  return <div className={`series-workspace${sheet ? " series-editor" : ""}`} onKeyDown={e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); void save() }
    if (e.key === 'Escape' && !(e.target instanceof Element && e.target.closest('[aria-modal="true"]'))) { setPanel(null); setPicker(null) }
  }}>
    <header className="series-heading"><div><Link to="/series">{text('Mes séries', 'My series')}</Link><h1>{sheet ? text('Ma série', 'My series') : text('Préparer ma série', 'Prepare my series')}</h1></div>
      {sheet && <div className="series-header-actions"><span className="series-privacy">{sheet.shared_with.length || !sheet.can_edit ? text('Partagée', 'Shared') : text('Privée', 'Private')}</span>
        {!mobile && <button disabled={!availableClips} onClick={() => openPlayer()}>{text('Voir la série', 'Watch series')} ({availableClips})</button>}
        {sheet.can_edit && <><button aria-expanded={panel === 'sharing'} onClick={() => { setPanel(panel === 'sharing' ? null : 'sharing'); setPicker(null) }}>{text('Partager', 'Share')}</button>{!mobile && <button className="series-primary" disabled={busy || !dirty || !sheet.title.trim()} onClick={save}>{busy ? text('Enregistrement…', 'Saving…') : text('Enregistrer', 'Save')}</button>}</>}
      </div>}
    </header>
    {error && <p role="alert" className="series-error">{error} <button onClick={() => {
      if (!dirty || window.confirm(text('Recharger et abandonner tes modifications ?', 'Reload and discard your changes?'))) setRevision(r => r + 1)
    }}>{text('Recharger', 'Reload')}</button></p>}
    {loading ? <p role="status">{text('Chargement…', 'Loading…')}</p> : !seriesId ? <>
      {eventTitle && <p className="series-notice">{eventTitle}</p>}
      <form className="series-create" onSubmit={async e => {
        e.preventDefault(); setBusy(true); setError('')
        try { const s = await seriesApi.create({ title: title.trim(), height, event_id: eventId ?? null, slots: sixSlots() }); navigate(`/series/${s.id}`) }
        catch (e) { failure(e) } finally { setBusy(false) }
      }}><h2>{text('Nouvelle série', 'New series')}</h2><div className="series-create-fields">
        <label>{text('Nom de la série', 'Series name')}<input required maxLength={160} value={title} onChange={e => setTitle(e.target.value)} placeholder={text('Ma série de printemps', 'My spring series')} /></label>
        <label>{text('Épreuve / hauteur', 'Event / height')}<select value={height} onChange={e => setHeight(e.target.value)}>{heights.map(h => <option key={h} value={h}>{Number.parseFloat(h) <= 3 ? text('Tremplin', 'Springboard') : text('Plateforme', 'Platform')} {h}</option>)}</select></label>
        <button className="series-primary" disabled={busy || !title.trim() || !eventReady}>{text('Créer ma série', 'Create my series')}</button>
      </div>
        {eventId && !eventReady && <p role="status">{text('Compétition inaccessible pour le moment.', 'Competition currently unavailable.')}</p>}
      </form>
      <h2>{text('Mes brouillons', 'My drafts')}</h2>
      {!items.length && <p>{text('Aucune série pour le moment.', 'No series yet.')}</p>}
      <ul className="series-list">{items.map(s => <li key={s.id}><Link to={`/series/${s.id}`}><strong>{s.title}</strong><span>{s.height} · {s.slot_count}{s.total_slots ? `/${s.total_slots}` : ''} {text('plongeons', 'dives')}</span></Link></li>)}</ul>
      {more && <button disabled={busy} onClick={async () => {
        setBusy(true); try { const rows = await seriesApi.list(eventId, (page + 1) * 50); setItems([...items, ...rows]); setPage(page + 1); setMore(rows.length === 50) } catch (e) { failure(e) } finally { setBusy(false) }
      }}>{text('Voir la suite', 'Load more')}</button>}
    </> : sheet && <>
      <div className="series-overview"><label className="series-name"><span className="sr-only">{text('Nom de la série', 'Series name')}</span><input value={sheet.title} maxLength={160} disabled={!sheet.can_edit || busy} onChange={e => { setSheet({ ...sheet, title: e.target.value }); setDirty(true); setNotice('') }} /></label>
        <div className="series-summary"><span className="series-height">{sheet.height}</span><span><b>{filled}/{sheet.slots.length}</b> {text('plongeons', 'dives')}</span><span><b>{totalDD.toFixed(1)}</b> {known.length < filled ? text('DD partiel', 'partial DD') : text('DD total', 'total DD')}</span></div>
      </div>
      {sheet.can_edit && <div className="series-clip-policy" data-policy={clipPolicy} role="group" aria-label={text('Sélection automatique des clips', 'Automatic clip selection')}>{(['best', 'recent'] as const).map(policy => <button key={policy} aria-pressed={clipPolicy === policy} disabled={busy} onClick={() => {
        if (policy === clipPolicy) return
        const refresh = (choice: SeriesChoice): SeriesChoice => ({ ...choice, dd: undefined, clip: choice.clip_id ? choice.clip : null })
        setSheet({ ...sheet, clip_policy: policy, slots: sheet.slots.map(s => ({ ...refresh(s), alternatives: s.alternatives.map(refresh) })) })
        setDirty(true); setNotice(''); setPicker(null)
      }}>{policy === 'best' ? text('Meilleurs clips', 'Best clips') : text('Plus récents', 'Most recent')}</button>)}</div>}
      {undoComparison && sheet.slots[undoComparison.index] === undoComparison.after && <div className="series-undo" role="status"><span>{text(`${undoComparison.after.code} dans ma série`, `${undoComparison.after.code} in my series`)}</span><button onClick={() => { change(undoComparison.index, undoComparison.before); setUndoComparison(null) }}>{text('Annuler', 'Undo')}</button></div>}
      {(notice || dirty) && <div className="series-status"><span role="status">{notice || text('Modifications non enregistrées', 'Unsaved changes')}</span></div>}
      <div className="series-board" role="region" aria-label={text('Série de plongeons', 'Dive series')} tabIndex={0}>
      <ol ref={board} className="series-cards" style={{ '--series-count': sheet.slots.length } as CSSProperties}>{sheet.slots.map((s, index) => {
        const c = resolved(s)
        return <SeriesCard key={index} index={index} code={s.code} dd={c.dd} videoId={c.clip?.video_uuid} className={`series-card${panel === index ? ' is-selected' : ''}${!s.code ? ' is-empty' : ''}`}>
          <div className="series-card-head"><span>{String(index + 1).padStart(2, '0')}</span><span>{sheet.height}</span>
            {sheet.can_edit && index === 5 && sheet.slots.length === 6 && <button className="series-remove-sixth" aria-label={text('Retirer le sixième plongeon', 'Remove sixth dive')} title={text('Passer à 5 plongeons', 'Switch to 5 dives')} disabled={busy} onClick={() => { removedSixth.current = s; mutate(sheet.slots.slice(0, 5)); if (panel === 5) setPanel(null) }}>×</button>}
          </div>
          <label className="series-code-label"><span className="sr-only">{text('Code du plongeon', 'Dive code')}</span><input ref={el => { inputs.current[index] = el }} aria-label={text(`Code du passage ${index + 1}`, `Dive ${index + 1} code`)} value={s.code} maxLength={5} disabled={!sheet.can_edit || busy} autoCapitalize="characters" autoComplete="off" spellCheck={false}
            onChange={e => enterCode(index, e.target.value, e.target.selectionStart)} onFocus={e => e.target.select()} onKeyDown={e => keyInCode(e, index)}
            onPaste={e => {
              const codes = e.clipboardData.getData('text').trim().toUpperCase().split(/[\s,;]+/)
              if (codes.length < 2) return
              e.preventDefault()
              if (codes.some(c => !isCode(c)) || codes.length > sheet.slots.length - index) {
                setError(text('Colle des codes séparés par des espaces, dans les places disponibles.', 'Paste space-separated dive codes within the available slots.')); return
              }
              const slots = sheet.slots.map((slot, i) => i >= index && i < index + codes.length ? { ...slot, code: codes[i - index], clip_id: null, dd: undefined, clip: null } : slot)
              mutate(slots); focus(Math.min(index + codes.length, slots.length - 1))
            }} placeholder="—" /></label>
          <p className="series-dive-name" title={diveName(s.code)} aria-live="polite">{diveName(s.code)}</p>
          <strong className="series-dd" aria-live="polite">{codeLabel(s)}</strong>
          <div className="series-card-media">{c.clip ? <button type="button" className="series-clip-trigger" onClick={() => openPlayer(index)} aria-label={text(`Voir le clip du passage ${index + 1}`, `View clip for dive ${index + 1}`)}>
            <MediaThumbnail posterUrl={previews[c.clip.video_uuid]?.poster_url} playbackUrl={previews[c.clip.video_uuid]?.playback_url} /><span>▶ {s.clip_id ? text('Mon choix', 'My choice') : clipPolicy === 'best' && seriesClipScore(c.clip) !== null ? text('Meilleur clip', 'Best clip') : text('Plus récent', 'Most recent')}{seriesClipScore(c.clip) !== null ? ` · ${seriesClipScore(c.clip)}/10` : ''}</span>
          </button> : <span>{s.code ? text('Pas de clip', 'No clip') : '—'}</span>}</div>
          <div className="series-card-foot"><button className="series-details" aria-expanded={panel === index} aria-controls="series-detail-panel" onClick={() => { setPanel(panel === index ? null : index); setPicker(null) }}>{s.alternatives.length ? text(`${s.alternatives.length} alternative${s.alternatives.length > 1 ? 's' : ''}`, `${s.alternatives.length} alternative${s.alternatives.length > 1 ? 's' : ''}`) : text('Options', 'Options')}</button>
            {sheet.can_edit && <div className="series-reorder"><button aria-label={text(`Monter le passage ${index + 1}`, `Move dive ${index + 1} up`)} title={text('Monter', 'Move up')} disabled={busy || index === 0} onClick={() => move(index, -1)}>{mobile ? '↑' : '←'}</button><button aria-label={text(`Descendre le passage ${index + 1}`, `Move dive ${index + 1} down`)} title={text('Descendre', 'Move down')} disabled={busy || index === sheet.slots.length - 1} onClick={() => move(index, 1)}>{mobile ? '↓' : '→'}</button></div>}
          </div>
        </SeriesCard>
      })}</ol></div>
      <div className="series-board-footer">
        {sheet.can_edit && sheet.slots.length === 5 && <button disabled={busy} onClick={() => mutate([...sheet.slots, removedSixth.current ?? blank()])}>{text('+ Rétablir le sixième plongeon', '+ Restore sixth dive')}</button>}
      </div>
      {selected && typeof panel === 'number' && <SeriesPanel className="series-detail-panel" id="series-detail-panel" label={text(`Options du passage ${panel + 1}`, `Options for dive ${panel + 1}`)} onClose={() => { setPanel(null); setPicker(null) }}>
        <div className="series-panel-heading"><h2>{text(`Passage ${panel + 1}`, `Dive ${panel + 1}`)} {selected.code && `· ${selected.code}`}</h2><button onClick={() => { setPanel(null); setPicker(null); focus(panel) }}>{text('Fermer', 'Close')} ×</button></div>
        <div className="series-panel-main"><div>{clipInfo(selected)}{sheet.can_edit && <button disabled={busy || !isCode(selected.code)} onClick={() => pick(panel, null, selected.code)}>{text('Choisir le clip', 'Choose clip')}</button>}</div>
          <div className="series-alternatives"><h3>{text('Mes alternatives', 'My alternatives')}</h3><div className="series-alternative-list">
            {selected.alternatives.map((a, ai) => <div className="series-alternative" key={ai}><label><span className="sr-only">{text('Code alternatif', 'Alternative code')}</span><input aria-label={text(`Alternative ${ai + 1} du passage ${panel + 1}`, `Alternative ${ai + 1} for dive ${panel + 1}`)} value={a.code} maxLength={5} autoCapitalize="characters" autoComplete="off" spellCheck={false} disabled={!sheet.can_edit || busy} onChange={e => change(panel, { alternatives: selected.alternatives.map((c, ci) => ci === ai ? { code: cleanCode(e.target.value), clip_id: null } : c) })} /></label><p className="series-dive-name" title={diveName(a.code)} aria-live="polite">{diveName(a.code)}</p><strong className="series-dd" aria-live="polite">{codeLabel(a)}</strong>
              {sheet.can_edit && <div className="series-actions"><button aria-label={text('Choisir ce plongeon', 'Use this dive')} disabled={busy || !isCode(a.code)} onClick={() => change(panel, { ...a, alternatives: selected.alternatives.map((c, ci) => ci === ai ? { code: selected.code, clip_id: selected.clip_id, dd: selected.dd, clip: selected.clip } : c) })}>{text('Utiliser', 'Use')}</button><button disabled={busy || !isCode(a.code) || !isCode(selected.code)} onClick={() => setComparison({ index: panel, alternative: ai, main: resolved(selected), candidate: resolved(a) })}>{text('Comparer', 'Compare')}</button><button disabled={busy || !isCode(a.code)} onClick={() => pick(panel, ai, a.code)}>{text('Clip', 'Clip')}</button><button aria-label={text(`Retirer l’alternative ${ai + 1}`, `Remove alternative ${ai + 1}`)} disabled={busy} onClick={() => change(panel, { alternatives: selected.alternatives.filter((_, ci) => ci !== ai) })}>×</button></div>}
            </div>)}
            {sheet.can_edit && selected.alternatives.length < 5 && <button className="series-add-alternative" disabled={busy} onClick={() => { change(panel, { alternatives: [...selected.alternatives, { code: '', clip_id: null }] }); requestAnimationFrame(() => document.getElementById('series-detail-panel')?.querySelectorAll('input').item(selected.alternatives.length)?.focus()) }}>{text('+ Garder une alternative', '+ Add alternative')}</button>}
          </div></div>
        </div>
      </SeriesPanel>}
      {picker && <SeriesPanel className="series-picker" layer={65} label={text('Choisir un clip', 'Choose a clip')} onClose={() => setPicker(null)}><div className="series-panel-heading"><h2>{text('Clips', 'Clips')} · {(picker.alternative === null ? sheet.slots[picker.index] : sheet.slots[picker.index].alternatives[picker.alternative]).code} · {sheet.height}</h2><button onClick={() => setPicker(null)}>{text('Fermer', 'Close')}</button></div>
        <button onClick={() => { const s = sheet.slots[picker.index]; if (picker.alternative === null) change(picker.index, { clip_id: null, clip: null }); else change(picker.index, { alternatives: s.alternatives.map((a, i) => i === picker.alternative ? { ...a, clip_id: null, clip: null } : a) }) }}>{text('Choix automatique', 'Automatic selection')}</button>
        {!picker.clips.length && <p>{text('Aucun clip disponible.', 'No clips available.')}</p>}
        {picker.clips.map(c => <div className="series-picker-row" key={c.id}><a href={c.url} target="_blank" rel="noreferrer">{text('Voir', 'View')} #{c.id}</a><span>{new Date(c.date).toLocaleDateString()} · {seriesClipScore(c) === null ? text('Sans note', 'Unrated') : `${seriesClipScore(c)}/10${c.rating_count ? ` (${c.rating_count})` : ''}`}</span><button onClick={() => { const s = sheet.slots[picker.index]; if (picker.alternative === null) change(picker.index, { clip_id: c.id, clip: c }); else change(picker.index, { alternatives: s.alternatives.map((a, i) => i === picker.alternative ? { ...a, clip_id: c.id, clip: c } : a) }) }}>{text('Choisir', 'Choose')}</button></div>)}
      </SeriesPanel>}
      {panel === 'sharing' && sheet.can_edit && <SeriesPanel className="series-sharing" label={text('Partager ma série', 'Share my series')} onClose={() => setPanel(null)}><div className="series-panel-heading"><h2>{text('Partager ma série', 'Share my series')}</h2><button onClick={() => setPanel(null)}>{text('Fermer', 'Close')}</button></div><p>{text('Lecture seule. Les vidéos privées restent privées.', 'Read only. Private videos remain private.')}</p>
        {sheet.shared_with.map(m => <div className="series-picker-row" key={m.id}><span>{m.name}</span><button disabled={busy || dirty} onClick={() => share(sheet.shared_with.filter(u => u.id !== m.id).map(u => u.id))}>{text('Retirer l’accès', 'Remove access')}</button></div>)}
        <label>{text('Rechercher un membre', 'Search members')}<input value={memberQuery} disabled={busy || dirty} onChange={e => setMemberQuery(e.target.value)} /></label>
        {dirty && <p>{text('Enregistre tes modifications avant de partager.', 'Save your changes before sharing.')}</p>}
        {members.filter(m => !sheet.shared_with.some(s => s.id === m.user_id)).map(m => <div className="series-picker-row" key={m.user_id}><span>{m.display_name}</span><button disabled={busy || dirty} onClick={() => share([...sheet.shared_with.map(u => u.id), m.user_id])}>{text('Donner accès', 'Grant access')}</button></div>)}
        {sheet.shared_with.length > 0 && <label>{text('Lien à transmettre', 'Link to share')}<input readOnly value={window.location.origin + '/series/' + sheet.id} onFocus={e => e.target.select()} /></label>}
      </SeriesPanel>}
      <details className="series-reference"><summary>{text('Référence DD', 'DD reference')}</summary><p>{sheet.dd_reference}</p></details>
      {mobile && <nav className="series-mobile-actions" aria-label={text('Actions de la série', 'Series actions')}>
        <button className="series-primary" disabled={!availableClips} onClick={() => openPlayer()}>{text('Voir la série', 'Watch series')} ({availableClips})</button>
        {sheet.can_edit && <button className="series-save" disabled={busy || !dirty || !sheet.title.trim()} onClick={save}>{busy ? text('Enregistrement…', 'Saving…') : text('Enregistrer', 'Save')}</button>}
      </nav>}
    </>}
    {comparison && sheet && <SeriesComparison main={comparison.main} alternative={comparison.candidate} height={sheet.height} policy={clipPolicy} previews={previews} onClose={() => setComparison(null)} onUse={(main, alternative) => {
      const before = sheet.slots[comparison.index]
      const after: SeriesSlot = { ...alternative, alternatives: before.alternatives.map((choice, i) => i === comparison.alternative ? main : choice) }
      mutate(sheet.slots.map((slot, i) => i === comparison.index ? after : slot))
      setUndoComparison({ index: comparison.index, before, after }); setComparison(null); setPanel(null)
      requestAnimationFrame(() => focus(comparison.index))
    }} />}
    {playback && <SeriesPlayer {...playback} onClose={() => setPlayback(null)} />}
  </div>
}
