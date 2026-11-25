import ImmersiveControls from '../clip-viewer/ImmersiveControls'
import '../clip-viewer/clipViewer.css'
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { reportPlaybackIssue, type SessionVideoInfo } from '../../services/sessionVideosApi'
import { canDecode, framesRendered } from './playability'

const FRAME_CHECK_AFTER_SECONDS = 1.5
const MAX_SOURCE_REFRESHES = 3

type Props = { info: SessionVideoInfo; playUrl: string; reportUrl: string; downloadFallback?: ReactNode }

/** Plays the untouched original; devices that cannot show it get a download. */
export default function SessionVideoPlayer({ info, playUrl, reportUrl, downloadFallback }: Props) {
  const { t } = useTranslation()
  const [state, setState] = useState<'checking' | 'playable' | 'unplayable'>('checking')
  const [fullscreenHint, setFullscreenHint] = useState(false)
  const [source, setSource] = useState(playUrl)
  const [rate,setRate] = useState(1)
  const video = useRef<HTMLVideoElement | null>(null)
  const attachVideo = useCallback((element: HTMLVideoElement | null) => {
    const previous = video.current
    video.current = element
    if (!element && previous) {
      previous.pause()
      previous.removeAttribute('src')
      previous.load()
    }
  }, [])
  const verified = useRef(false)
  const hasMetadata = useRef(false)
  const reported = useRef(false)
  const refreshes = useRef(0)
  const recovering = useRef(false)
  const resumeAt = useRef(0)
  const playing = useRef(false)
  const initialPlayRequested = useRef(false)
  const resumePlayback = useRef(false)

  const giveUp = (reason: 'unsupported' | 'no_frames' | 'error') => {
    if (!reported.current) { reported.current = true; reportPlaybackIssue(reportUrl, reason) }
    video.current?.pause()
    setState('unplayable')
  }

  useEffect(() => {
    let alive = true
    verified.current = false; hasMetadata.current = false; reported.current = false; refreshes.current = 0; resumeAt.current = 0
    playing.current = false; recovering.current = false; resumePlayback.current = false
    initialPlayRequested.current = false
    setSource(playUrl); setState('checking'); setFullscreenHint(false)
    canDecode(info).then(ok => {
      if (!alive) return
      if (ok) setState('playable')
      else { reported.current = true; reportPlaybackIssue(reportUrl, 'unsupported'); setState('unplayable') }
    })
    return () => { alive = false }
  }, [info, playUrl, reportUrl])

  const refreshing = source !== playUrl
  useLayoutEffect(() => {
    // The normal player leaves the original untouched until Play. A replacement
    // after a failed Range request must load its metadata to resume playback.
    if (refreshing) video.current?.load()
  }, [source, refreshing])

  if (state === 'checking') return <div className="session-video-frame session-video-loading" aria-busy="true">
    {info.poster_url && <img src={info.poster_url} alt="" />}
    <span className="page-loading-indicator" role="status" aria-label={t('sessionVideo.loading')} />
  </div>
  if (state === 'unplayable') {
    return <div className="session-video-frame session-video-unplayable">
      <p role="status">{t('sessionVideo.unplayable')}</p>
      {downloadFallback}
    </div>
  }
  return <div className="session-video-frame">
    <div className="session-video-picture"><video
      ref={attachVideo}
      src={source}
      controls={false}
      playsInline
      poster={info.poster_url}
      preload={refreshing ? 'metadata' : 'none'}
      aria-label={t('sessionVideo.videoAria')}
      onLoadedMetadata={event => {
        hasMetadata.current = true
        initialPlayRequested.current = false
        setFullscreenHint(false)
        const element = event.currentTarget
        element.playbackRate = rate
        if (resumeAt.current) element.currentTime = resumeAt.current
      }}
      onPlay={() => { playing.current = true }}
      onPause={event => {
        // A failed load can pause the element before its error handler runs.
        if (!event.currentTarget.error && !resumePlayback.current) playing.current = false
      }}
      onCanPlay={event => {
        if (!recovering.current) return
        recovering.current = false
        resumeAt.current = 0
        if (!resumePlayback.current) return
        resumePlayback.current = false
        // Autoplay policy may reject resuming; the play button remains usable.
        void event.currentTarget.play().catch(() => {})
      }}
      onTimeUpdate={event => {
        const element = event.currentTarget
        if (verified.current || element.currentTime < FRAME_CHECK_AFTER_SECONDS) return
        if (framesRendered(element)) verified.current = true
        else giveUp('no_frames')
      }}
      onError={event => {
        const element = event.currentTarget
        const code = element.error?.code
        // Browsers also use code 4 for an HTTP failure before metadata.
        const retryLimit = code === 4 && !hasMetadata.current ? 1 : MAX_SOURCE_REFRESHES
        if ((code === 2 || code === 4) && refreshes.current < retryLimit) {
          // Network error, e.g. the signed B2 URL expired mid-session: ask
          // for a fresh one and resume where the viewer was.
          refreshes.current += 1
          if (!recovering.current) {
            resumeAt.current = element.currentTime
            resumePlayback.current = playing.current || initialPlayRequested.current
          }
          recovering.current = true
          setSource(`${playUrl}${playUrl.includes('?') ? '&' : '?'}r=${refreshes.current}`)
          return
        }
        if (code === 2 || code === 3 || code === 4) giveUp('error')
      }}
    /></div>
    {fullscreenHint && <p className="session-fullscreen-hint" role="status">{t('clipViewer.fullscreenAfterPlay')}</p>}
    <ImmersiveControls onFullscreenPending={() => setFullscreenHint(true)}
      onPlayRequested={() => { if (!hasMetadata.current) initialPlayRequested.current = true }} videoRef={video} durationHint={info.duration_seconds ?? null} playbackRate={rate}
      onPlaybackRateChange={value => { setRate(value); if (video.current) video.current.playbackRate = value }} />
  </div>
}
