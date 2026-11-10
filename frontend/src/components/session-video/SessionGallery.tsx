import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Download, Lock, Settings, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import DiveThumbnail from '../DiveThumbnail'
import type { Attempt } from '../../utils/attemptPresentation'
import SessionVideoPlayer from './SessionVideoPlayer'
import ShareDiveButton from '../clip-viewer/ShareDiveButton'
import { api } from '../../services/api'
import { formatBytes, formatDuration, sessionVideoPaths, type SharedTrainingSession, type SessionVideoInfo } from '../../services/sessionVideosApi'
import './sessionVideo.css'
import '../clip-viewer/clipViewer.css'

export function SessionPoster({ video }: { video: SessionVideoInfo }) {
  return <DiveThumbnail compact dive={{ id: video.id, thumb_url: video.poster_url, animated_url: video.animated_url } as Attempt} />
}

type Props = { session: SharedTrainingSession; guest?: boolean; onSignup?: () => void; reload?: () => void; guestBase?: string }

// A new session or guest capability owns a new workspace. No pending response,
// selection or download sequence can leak into its successor.
export default function SessionGallery(props: Props) {
  return <GalleryWorkspace key={`${props.session.session_id}:${props.guestBase ?? 'member'}`} {...props} />
}

function GalleryWorkspace({ session, guest = false, onSignup, reload, guestBase }: Props) {
  const { t, i18n } = useTranslation()
  const [selected, select] = useState<number | null>(null)
  const [deleteCandidate, setDeleteCandidate] = useState<number | null>(null)
  const [settings, showSettings] = useState(false)
  const [busy, setBusy] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')
  const [moveDate, setMoveDate] = useState('')
  const [videos, setVideos] = useState(session.videos)
  const [next, setNext] = useState(session.next_video_id)
  const alive = useRef(true)
  const paging = useRef(false)
  const working = useRef(false)
  const downloadGeneration = useRef(0)
  const generation = useRef(0)
  const playerSlot = useRef<HTMLDivElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const tileButtons = useRef(new Map<number, HTMLButtonElement>())
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false; generation.current++; downloadGeneration.current++ }
  }, [])
  useEffect(() => {
    generation.current++
    downloadGeneration.current++
    paging.current = false; working.current = false
    setLoadingMore(false); setBusy(false); setDownloading(false); setDeleteCandidate(null); setError('')
    setVideos(session.videos); setNext(session.next_video_id)
    select(current => session.videos.some(v => v.id === current) ? current : null)
  }, [session])
  const pageUrl = guest ? `${guestBase}/recordings` : `/api/v1/shared-sessions/${session.session_id}`
  const video = videos.find(v => v.id === selected)
  const index = videos.findIndex(v => v.id === selected)
  const canManage = !guest && (session.can_manage || videos.some(v => v.can_share))
  const date = new Intl.DateTimeFormat(i18n.language, { weekday: 'long', day: 'numeric', month: 'long' }).format(new Date(`${session.date}T12:00:00`))
  const singleVideo = session.video_count === 1 && !next
  useLayoutEffect(() => {
    const slot = playerSlot.current
    if (!slot) return
    const resize = () => slot.style.setProperty('--session-player-max-height', `${Math.max(220, Math.min(window.innerHeight * .65, 680))}px`)
    resize()
    window.addEventListener('resize', resize)
    return () => window.removeEventListener('resize', resize)
  }, [video?.id])
  useEffect(() => { if (video) heading.current?.focus() }, [video?.id])

  async function more() {
    if (paging.current || next == null) return
    paging.current = true; setLoadingMore(true); setError('')
    const requestGeneration = generation.current
    try {
      const { data } = await api.get<SharedTrainingSession>(pageUrl, { params: { after: next } })
      if (!alive.current || requestGeneration !== generation.current) return
      setVideos(current => {
        const ids = new Set(current.map(v => v.id))
        return [...current, ...data.videos.filter(v => !ids.has(v.id))]
      })
      setNext(data.next_video_id)
    } catch { if (alive.current && requestGeneration === generation.current) setError(t('sessionVideo.loadError')) }
    finally { if (alive.current && requestGeneration === generation.current) { paging.current = false; setLoadingMore(false) } }
  }
  async function edit(id: number, payload: object) {
    if (working.current) return
    working.current = true; setBusy(true); setError('')
    const requestGeneration = generation.current
    try {
      await api.patch(`/api/v1/session-videos/${id}`, payload)
      if (!alive.current || requestGeneration !== generation.current) return
      select(null); reload?.()
    } catch { if (alive.current && requestGeneration === generation.current) setError(t('sessionVideo.editError')) }
    finally { if (alive.current && requestGeneration === generation.current) { working.current = false; setBusy(false) } }
  }
  function downloadOne(item: SessionVideoInfo) {
    if (guest) { onSignup?.(); return }
    const anchor = document.createElement('a')
    anchor.href = sessionVideoPaths(item.id).download; anchor.download = item.filename
    anchor.target = '_blank'; anchor.rel = 'noopener'
    document.body.append(anchor); anchor.click(); anchor.remove()
  }
  function cancelDownloads() {
    downloadGeneration.current++; working.current = false; setBusy(false); setDownloading(false)
  }
  async function downloadAll() {
    if (guest) { onSignup?.(); return }
    if (working.current) return
    working.current = true; setBusy(true); setError('')
    setDownloading(true)
    const run = ++downloadGeneration.current
    const current = () => alive.current && run === downloadGeneration.current
    const seen = new Set<number>()
    const cursors = new Set<number>()
    try {
      let page = videos, cursor = next
      while (current()) {
        for (const item of page) {
          if (!current()) return
          if (seen.has(item.id)) continue
          seen.add(item.id); downloadOne(item)
          await new Promise(resolve => setTimeout(resolve, 1000))
        }
        if (!current() || cursor == null) break
        if (cursors.has(cursor)) throw new Error('Repeated pagination cursor')
        cursors.add(cursor)
        const { data } = await api.get<SharedTrainingSession>(pageUrl, { params: { after: cursor } })
        page = data.videos; cursor = data.next_video_id
      }
    } catch { if (current()) setError(t('sessionVideo.downloadError')) }
    finally { if (current()) { working.current = false; setBusy(false); setDownloading(false) } }
  }
  function closePlayer() {
    const previous = selected
    select(null)
    requestAnimationFrame(() => { if (previous != null) tileButtons.current.get(previous)?.focus() })
  }
  const otherVideos = video && !settings ? videos.filter(item => item.id !== video.id) : videos
  return <section className={`session-gallery${video ? ' has-player' : ''}`} aria-label={t('sessionVideo.title')}>
    <header className="session-gallery-header">
      <div><h1>{session.title || date}</h1><p>{t('sessionVideo.recordings', { count: session.video_count })}{session.total_duration ? ` · ${formatDuration(session.total_duration)}` : ''}</p></div>
      {canManage && <div className="session-video-actions">
        <ShareDiveButton id={session.session_id} sharesPath={`/api/v1/shared-sessions/${session.session_id}/shares`} label={t('sessionVideo.share')} />
        <button type="button" aria-label={t('sessionVideo.settings')} aria-pressed={settings} onClick={() => showSettings(!settings)}><Settings size={20} /></button>
      </div>}
    </header>
    <div className="session-workspace">
      {video && <section className="session-selected" aria-label={t('sessionVideo.videoAria')}>
        <div className="session-player-heading"><h2 ref={heading} tabIndex={-1}>{video.filename}</h2><button type="button" aria-label={t('sessionVideo.closePlayer')} onClick={closePlayer}><X size={20} /></button></div>
        <div ref={playerSlot} className="session-player-slot"><SessionVideoPlayer key={video.id} info={video}
          playUrl={guest ? (video as SessionVideoInfo & { video_url: string }).video_url : sessionVideoPaths(video.id).play}
          downloadUrl={guest ? '' : sessionVideoPaths(video.id).download} onDownload={guest ? onSignup : undefined}
          reportUrl={guest ? `${guestBase}/videos/${video.id}/playback-issues` : sessionVideoPaths(video.id).report} showFallbackDownload={false} /></div>
        <div className="session-player-navigation">
          <button type="button" disabled={index <= 0} aria-label={t('sessionVideo.previous')} onClick={() => select(videos[index - 1].id)}><ChevronLeft size={20} /></button>
          <span>{t('sessionVideo.position', { current: index + 1, total: session.video_count })}</span>
          <button type="button" disabled={index >= videos.length - 1} aria-label={t('sessionVideo.next')} onClick={() => select(videos[index + 1].id)}><ChevronRight size={20} /></button>
          {!singleVideo && <button type="button" className="session-video-download" onClick={() => downloadOne(video)}>{guest ? <Lock size={16} /> : <Download size={16} />}{t('sessionVideo.download', { size: formatBytes(video.size_bytes, i18n.language) })}</button>}
        </div>
      </section>}
      {(otherVideos.length > 0 || next != null) && <div className="session-recordings" aria-label={t('sessionVideo.recordings', { count: session.video_count })}>
        <div className="session-recording-grid">
          {otherVideos.map(item => <div key={item.id} className="session-tile">
            <button type="button" ref={node => { if (node) tileButtons.current.set(item.id, node); else tileButtons.current.delete(item.id) }} aria-label={t('sessionVideo.playRecording', { name: item.filename })} aria-pressed={item.id === selected} onClick={() => select(item.id)}>
              <div className="session-poster"><SessionPoster video={item} /><span className="session-duration">{formatDuration(item.duration_seconds)}</span></div>
              <strong title={item.filename}>{item.filename}</strong>
              <span>{item.recorded_at ? new Date(item.recorded_at).toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit' }) : formatBytes(item.size_bytes, i18n.language)}{item.hidden ? ` · ${t('sessionVideo.hidden')}` : ''}</span>
            </button>
            {settings && item.can_share && <div className="session-settings">
              <button type="button" disabled={busy} onClick={() => edit(item.id, { hidden: !item.hidden })}>{t(item.hidden ? 'sessionVideo.show' : 'sessionVideo.hide')}</button>
              {deleteCandidate === item.id ? <div className="session-delete-confirm" role="group" aria-label={t('sessionVideo.confirmDelete')}>
                <p>{t('sessionVideo.confirmDelete')}</p>
                <button type="button" disabled={busy} onClick={() => { setDeleteCandidate(null); void edit(item.id, { delete: true }) }}>{t('sessionVideo.delete')}</button>
                <button type="button" onClick={() => setDeleteCandidate(null)}>{t('sessionVideo.cancel')}</button>
              </div> : <button type="button" disabled={busy} onClick={() => setDeleteCandidate(item.id)}>{t('sessionVideo.delete')}</button>}
              <input aria-label={t('sessionVideo.destinationDate')} type="date" value={moveDate} onChange={event => setMoveDate(event.target.value)} />
              <button type="button" disabled={busy || !moveDate} onClick={() => edit(item.id, { date: moveDate })}>{t('sessionVideo.move')}</button>
            </div>}
          </div>)}
        </div>
        {next != null && <button type="button" className="session-load-more" disabled={loadingMore} onClick={more}>{t(loadingMore ? 'sessionVideo.loading' : 'sessionVideo.loadMore')}</button>}
      </div>}
    </div>
    {!videos.length && <p role="status">{t('sessionVideo.empty')}</p>}
    {error && <p className="session-gallery-error" role="alert">{error}</p>}
    <footer className="session-gallery-footer">
      <button type="button" className="session-download-all" disabled={busy || !session.video_count} onClick={downloadAll}>{guest ? <Lock size={18} /> : <Download size={18} />}{t(singleVideo ? 'sessionVideo.download' : 'sessionVideo.downloadAll', { size: formatBytes(session.total_bytes, i18n.language) })}</button>
      {downloading && <button type="button" onClick={cancelDownloads}>{t('sessionVideo.stopDownloads')}</button>}
    </footer>
  </section>
}
