import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { Download, Lock, Play, Settings, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import DiveThumbnail from '../DiveThumbnail'
import type { Attempt } from '../../utils/attemptPresentation'
import SessionViewer from './SessionViewer'
import SessionDownloadAccess from './SessionDownloadAccess'
import ShareDiveButton from '../clip-viewer/ShareDiveButton'
import { api } from '../../services/api'
import { formatBytes, formatDuration, formatRecordingDuration, type SharedTrainingSession, type SessionVideoInfo } from '../../services/sessionVideosApi'
import { useSessionDownloads } from './useSessionDownloads'
import { useSessionHistory } from './useSessionHistory'
import './sessionVideo.css'

export function SessionPoster({ video }: { video: SessionVideoInfo }) {
  return <DiveThumbnail compact dive={{ id: video.id, thumb_url: video.poster_url, animated_url: video.animated_url } as Attempt} />
}

export type DownloadTarget = number | 'all'
type Props = {
  session: SharedTrainingSession
  guest?: boolean
  onSignup?: (target: DownloadTarget) => void
  onLogin?: (target: DownloadTarget) => void
  restoreDownloadFocus?: DownloadTarget
  onDownloadFocusRestored?: () => void
  suspended?: boolean
  reload?: () => void
  guestBase?: string
}

// A new session or guest capability owns a new workspace. No pending response,
// selection or download sequence can leak into its successor.
export default function SessionGallery(props: Props) {
  return <GalleryWorkspace key={`${props.session.session_id}:${props.guestBase ?? 'member'}`} {...props} />
}

function GalleryWorkspace({
  session, guest = false, onSignup, onLogin, restoreDownloadFocus, onDownloadFocusRestored, suspended = false, reload, guestBase,
}: Props) {
  const { t, i18n } = useTranslation()
  const history = useSessionHistory()
  const { location } = history
  const currentEntry = useRef(location.key)
  currentEntry.current = location.key
  const [deleteCandidate, setDeleteCandidate] = useState<number | null>(null)
  const [settings, showSettings] = useState(false)
  const [busy, setBusy] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')
  const [downloadError, setDownloadError] = useState<{ message: string; fromViewer: boolean }>()
  const [viewerError, setViewerError] = useState('')
  const [moveDate, setMoveDate] = useState('')
  const [videos, setVideos] = useState(session.videos)
  const [next, setNext] = useState(session.next_video_id)
  const [loadedPages, setLoadedPages] = useState(1)
  const [totals, setTotals] = useState(session)
  const alive = useRef(true)
  const paging = useRef<{ controller: AbortController; viewerEntry?: string } | null>(null)
  const working = useRef(false)
  const generation = useRef(0)
  const gallery = useRef<HTMLElement>(null)
  const dock = useRef<HTMLElement>(null)
  const playerOpener = useRef<HTMLButtonElement | null>(null)
  const downloadOpener = useRef<HTMLElement | null>(null)
  const fileDescription = useId()
  const pageUrl = guest ? `${guestBase}/recordings` : `/api/v1/shared-sessions/${session.session_id}`
  const videoCount = Math.max(totals.video_count, videos.length)
  const { download, failed, requestedCount, reset, start, stop } = useSessionDownloads(pageUrl, videos, next, videoCount)
  const batch = download?.kind === 'batch' ? download : null
  const marker = location.state?.sessionViewer
  const accessMarker = location.state?.sessionDownloadAccess
  const downloadAccess: DownloadTarget | null = guest && !suspended && accessMarker?.sessionId === session.session_id ? accessMarker.target : null
  const selectedId = marker?.sessionId === session.session_id ? marker.videoId : null
  const index = videos.findIndex(v => v.id === selectedId)
  const video = videos[index]
  const canManage = !guest && (session.can_manage || videos.some(v => v.can_share))
  const date = new Intl.DateTimeFormat(i18n.language, { weekday: 'long', day: 'numeric', month: 'long' }).format(new Date(`${session.date}T12:00:00`))
  const singleVideo = videoCount === 1 && next == null
  const multipleVideos = videoCount > 0 && !singleVideo
  const DownloadIcon = guest ? Lock : Download
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false; generation.current++; paging.current?.controller.abort() }
  }, [])
  useEffect(() => {
    generation.current++
    paging.current?.controller.abort()
    paging.current = null
    working.current = false
    reset()
    setLoadingMore(false); setBusy(false); setDeleteCandidate(null); setError(''); setDownloadError(undefined)
    setVideos(session.videos); setNext(session.next_video_id); setTotals(session); setLoadedPages(1)
  }, [session, reset])
  useLayoutEffect(() => {
    const footer = dock.current
    const section = gallery.current
    if (!footer || !section) return
    const measure = () => section.style.setProperty('--session-dock-height', `${footer.offsetHeight}px`)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(footer)
    return () => { observer.disconnect(); section.style.removeProperty('--session-dock-height') }
  }, [multipleVideos])
  useLayoutEffect(() => {
    if (suspended || restoreDownloadFocus === undefined || video) return
    const action = `[data-download-target="${restoreDownloadFocus}"]`
    const control = gallery.current?.querySelector<HTMLElement>(action)
      ?? gallery.current?.querySelector<HTMLElement>('[data-download-target="all"]')
    control?.focus({ preventScroll: true })
    onDownloadFocusRestored?.()
  }, [onDownloadFocusRestored, restoreDownloadFocus, suspended, video])
  useLayoutEffect(() => {
    setViewerError('')
    return () => {
      if (paging.current?.viewerEntry === location.key) paging.current.controller.abort()
    }
  }, [location.key])

  useEffect(() => {
    if (!selectedId || video || suspended) return
    // Replay only the prefix the viewer had already reached. Stop at the
    // recorded id; each fetch is a bounded page and leaving cancels it.
    if (next != null && next < selectedId && loadedPages < marker.loadedPages) void more(false, true)
    else {
      setError(t('sessionVideo.unavailable'))
      history.change({ sessionViewer: undefined }, true)
    }
  }, [loadedPages, location.key, next, selectedId, suspended, video])

  function openVideo(id: number, replace = false, pages = loadedPages) {
    history.change({ sessionViewer: { sessionId: session.session_id, videoId: id, loadedPages: pages } }, replace)
  }
  const closeViewer = () => history.close('sessionViewer')
  const closeAccess = () => history.close('sessionDownloadAccess')

  async function more(advance = false, restore = false) {
    if (paging.current || next == null) return
    const controller = new AbortController()
    const request = { controller, viewerEntry: advance || restore ? location.key : undefined }
    paging.current = request
    const setPageError = advance ? setViewerError : setError
    setLoadingMore(true); setPageError('')
    try {
      const { data } = await api.get<SharedTrainingSession>(pageUrl, { params: { after: next }, signal: controller.signal })
      if (controller.signal.aborted) return
      if (data.next_video_id != null && data.next_video_id <= next) throw new Error('Nonadvancing recording page')
      const ids = new Set(videos.map(v => v.id))
      const added = data.videos.filter(item => {
        if (ids.has(item.id)) return false
        ids.add(item.id)
        return true
      })
      setVideos(current => [...current, ...added])
      setNext(data.next_video_id)
      setLoadedPages(loadedPages + 1)
      setTotals(data)
      const nextVideo = added[0]
      if (advance && nextVideo && currentEntry.current === location.key) openVideo(nextVideo.id, true, loadedPages + 1)
    } catch {
      if (!controller.signal.aborted) {
        setPageError(t('sessionVideo.loadError'))
        if (restore) history.change({ sessionViewer: undefined }, true)
      }
    }
    finally {
      if (paging.current === request) {
        paging.current = null
        if (alive.current) setLoadingMore(false)
      }
    }
  }
  async function edit(id: number, payload: object) {
    if (working.current || download) return
    working.current = true; setBusy(true); setError('')
    const requestGeneration = generation.current
    try {
      await api.patch(`/api/v1/session-videos/${id}`, payload)
      if (!alive.current || requestGeneration !== generation.current) return
      reload?.()
    } catch { if (alive.current && requestGeneration === generation.current) setError(t('sessionVideo.editError')) }
    finally { if (alive.current && requestGeneration === generation.current) { working.current = false; setBusy(false) } }
  }
  function requestDownload(button: HTMLButtonElement, item?: SessionVideoInfo) {
    if (guest) {
      downloadOpener.current = button
      history.change({ sessionDownloadAccess: { sessionId: session.session_id, target: item?.id ?? 'all' } })
      return
    }
    if (working.current || download) return
    setDownloadError(undefined)
    void start(item, failureCount => {
      const message = t(failureCount === 'busy' ? 'sessionVideo.downloadBusy' : item ? 'sessionVideo.downloadFileError' : failureCount ? 'sessionVideo.downloadPartial' : 'sessionVideo.downloadError', { count: typeof failureCount === 'number' ? failureCount : undefined })
      setDownloadError({ message, fromViewer: !!video || !item })
    })
  }
  const totalSize = formatBytes(totals.total_bytes, i18n.language)
  const preparing = download?.kind === 'file'
  const retrySingle = singleVideo && videos[0] && failed.has(videos[0].id)
  const resuming = !singleVideo && requestedCount > 0
  const primaryDownload = <button type="button" className="session-download-all"
    disabled={singleVideo && !videos.length} aria-disabled={busy || preparing || undefined} aria-busy={singleVideo && preparing || undefined}
    aria-haspopup={guest ? 'dialog' : undefined} data-download-target="all"
    onClick={event => batch ? stop() : requestDownload(event.currentTarget, singleVideo ? videos[0] : undefined)}>
    {batch ? <X size={19} aria-hidden /> : <DownloadIcon size={19} aria-hidden />}
    <span>{t(batch ? 'sessionVideo.stopDownloads' : guest ? 'sessionVideo.downloadSignIn' : singleVideo && preparing ? 'sessionVideo.preparingDownload' : retrySingle ? 'sessionVideo.retryDownload' : singleVideo ? 'sessionVideo.downloadVideo' : resuming ? 'sessionVideo.downloadRemaining' : 'sessionVideo.downloadAll', { count: Math.max(1, videoCount - requestedCount) })}</span>
    {!batch && !resuming && totalSize && <span className="session-download-size">{totalSize}</span>}
  </button>
  function fileDownload(item: SessionVideoInfo, variant: 'row' | 'header' | 'fallback' = 'row') {
    const size = formatBytes(item.size_bytes, i18n.language)
    const fallback = variant === 'fallback'
    const retry = failed.has(item.id)
    const pending = download?.kind === 'file' && download.id === item.id
    const action = t(guest ? 'sessionVideo.downloadSignIn' : pending ? 'sessionVideo.preparingDownload' : retry ? 'sessionVideo.retryDownload' : 'sessionVideo.downloadVideo')
    const label = fallback ? action : t(guest ? 'sessionVideo.downloadSignInFile' : pending ? 'sessionVideo.preparingDownload' : retry ? 'sessionVideo.retryDownloadFile' : 'sessionVideo.downloadFile', { name: item.filename })
    return <button type="button" className="session-file-download"
      title={action} aria-label={size ? `${label} · ${size}` : label} data-download-target={item.id} aria-busy={pending || undefined}
      aria-disabled={busy || !!download || undefined} aria-haspopup={guest ? 'dialog' : undefined} onClick={event => requestDownload(event.currentTarget, item)}>
      {pending ? <span className="page-loading-indicator" aria-hidden /> : <DownloadIcon size={19} aria-hidden />}
      {fallback && <span>{action}</span>}
      {(fallback || (variant === 'header' && singleVideo)) && size && <span>{size}</span>}
    </button>
  }
  const progress = batch && <p className="session-download-progress" role="status">{t('sessionVideo.downloadProgress', { current: batch.requested, total: videoCount })}</p>
  const galleryError = !video && (error || downloadError?.message)
  const retryOnLaterPage = next != null && downloadError && [...failed].some(id => id > next)
  const alert = galleryError && <p className="session-gallery-error" role="alert">
    {galleryError}{retryOnLaterPage && ` ${t('sessionVideo.downloadRetryMore', { action: t('sessionVideo.loadMore') })}`}
  </p>
  return <>
    <section ref={gallery} className={`session-gallery${multipleVideos ? ' session-gallery-multiple' : ''}`}
      onFocusCapture={event => {
        if (!dock.current || getComputedStyle(dock.current).position !== 'fixed' || !event.target.closest('.session-recordings')) return
        const target = event.target
        requestAnimationFrame(() => {
          if (document.activeElement !== target || !dock.current) return
          const overlap = target.getBoundingClientRect().bottom - dock.current.getBoundingClientRect().top + 8
          if (overlap > 0) window.scrollBy(0, overlap)
        })
      }}
      aria-label={t('sessionVideo.title')} aria-hidden={video || downloadAccess !== null ? true : undefined}>
      <header className="session-gallery-header">
        <h1>{session.title || date}</h1>
        {(session.title || canManage) && <div className="session-gallery-meta">
          {session.title && <p>{date}</p>}
          {canManage && <div className="session-video-actions">
            <ShareDiveButton id={session.session_id} sharesPath={`/api/v1/shared-sessions/${session.session_id}/shares`} label={t('sessionVideo.share')} />
            <button type="button" aria-label={t('sessionVideo.settings')} aria-pressed={settings} onClick={() => showSettings(!settings)}><Settings size={19} aria-hidden /></button>
          </div>}
        </div>}
      </header>
      {singleVideo && <div className="session-primary-actions">{primaryDownload}{alert}</div>}
      {multipleVideos && <footer ref={dock} className="session-gallery-footer">
        {alert}
        {progress}
        {primaryDownload}
      </footer>}
      {!singleVideo && !multipleVideos && alert}
      {(videos.length > 0 || next != null) && <div className="session-recordings">
        {multipleVideos && <div className="session-recordings-heading">
          <h2>{t('sessionVideo.recordings', { count: videoCount })}</h2>
          {totals.total_duration > 0 && <span>{formatDuration(totals.total_duration)}</span>}
        </div>}
        <ul className={singleVideo ? 'session-feature' : 'session-file-list'}>
          {videos.map(item => {
            const time = item.recorded_at ? new Date(item.recorded_at).toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit' }) : ''
            const duration = formatRecordingDuration(item.duration_seconds)
            const detail = [time, !singleVideo && duration, !singleVideo && formatBytes(item.size_bytes, i18n.language), failed.has(item.id) && t('sessionVideo.downloadNeedsRetry'), item.hidden && t('sessionVideo.hidden')].filter(Boolean)
            return <li key={item.id} className="session-file">
              <div className="session-file-main">
                <button type="button" className="session-file-open" aria-label={t(singleVideo ? 'sessionVideo.watchRecording' : 'sessionVideo.playRecording', { name: item.filename })}
                  aria-describedby={(detail.length > 0 || duration) ? `${fileDescription}-${item.id}` : undefined}
                  aria-haspopup="dialog" onClick={event => { playerOpener.current = event.currentTarget; openVideo(item.id) }}>
                  <div className="session-poster" aria-hidden="true">
                    <SessionPoster video={item} />
                    {singleVideo && <><span className="session-watch"><Play size={15} fill="currentColor" />{t('sessionVideo.watch')}</span>
                      {duration && <span className="session-duration">{duration}</span>}</>}
                  </div>
                  <span className="session-file-info"><strong title={item.filename}>{item.filename}</strong>
                    {(detail.length > 0 || duration) && <small id={`${fileDescription}-${item.id}`}>
                      {singleVideo && duration && <span className="sr-only">{duration}{detail.length > 0 && ' · '}</span>}
                      {detail.map((value, i) => <span className="session-file-detail" key={i}>{i > 0 && ' · '}{value}</span>)}
                    </small>}
                  </span>
                  {!singleVideo && <span className="session-row-play"><Play size={16} fill="currentColor" aria-hidden /></span>}
                </button>
                {!singleVideo && fileDownload(item)}
              </div>
              {settings && item.can_share && <div className="session-settings">
                <button type="button" disabled={busy || !!download} onClick={() => edit(item.id, { hidden: !item.hidden })}>{t(item.hidden ? 'sessionVideo.show' : 'sessionVideo.hide')}</button>
                {deleteCandidate === item.id ? <div className="session-delete-confirm" role="group" aria-label={t('sessionVideo.confirmDelete')}>
                  <p>{t('sessionVideo.confirmDelete')}</p>
                  <button type="button" disabled={busy || !!download} onClick={() => { setDeleteCandidate(null); void edit(item.id, { delete: true }) }}>{t('sessionVideo.delete')}</button>
                  <button type="button" onClick={() => setDeleteCandidate(null)}>{t('sessionVideo.cancel')}</button>
                </div> : <button type="button" disabled={busy || !!download} onClick={() => setDeleteCandidate(item.id)}>{t('sessionVideo.delete')}</button>}
                <input aria-label={t('sessionVideo.destinationDate')} type="date" value={moveDate} onChange={event => setMoveDate(event.target.value)} />
                <button type="button" disabled={busy || !!download || !moveDate} onClick={() => edit(item.id, { date: moveDate })}>{t('sessionVideo.move')}</button>
              </div>}
            </li>
          })}
        </ul>
        {next != null && <button type="button" className="session-load-more" disabled={loadingMore} onClick={() => void more()}>{t(loadingMore ? 'sessionVideo.loading' : 'sessionVideo.loadMore')}</button>}
      </div>}
      {!videos.length && <p role="status">{t('sessionVideo.empty')}</p>}
    </section>
    {video && !suspended && <SessionViewer video={video} guestBase={guestBase} opener={playerOpener}
      fallbackFocus={() => gallery.current?.querySelector<HTMLButtonElement>('[data-download-target="all"]') ?? null}
      onClose={closeViewer} hidden={downloadAccess !== null} error={viewerError || (downloadError?.fromViewer ? downloadError.message : '')}
      batch={batch ? <>{progress}{primaryDownload}</> : undefined}
      download={fileDownload(video, 'header')} downloadFallback={fileDownload(video, 'fallback')}
      restoreDownloadFocus={restoreDownloadFocus === video.id ? onDownloadFocusRestored : undefined}
      navigation={multipleVideos ? {
        position: index + 1, total: videoCount, loading: loadingMore,
        previous: index > 0 ? () => openVideo(videos[index - 1].id, true) : undefined,
        next: index < videos.length - 1 ? () => openVideo(videos[index + 1].id, true) : next != null ? () => void more(true) : undefined,
      } : undefined} />}
    {downloadAccess !== null && <SessionDownloadAccess opener={downloadOpener} onClose={closeAccess}
      onLogin={() => onLogin?.(downloadAccess)}
      onSignup={() => onSignup?.(downloadAccess)} />}
  </>
}
