import ImmersiveControls from '../clip-viewer/ImmersiveControls'
import '../clip-viewer/clipViewer.css'
import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'
import { Download } from 'lucide-react'
import { formatBytes, reportPlaybackIssue, type SessionVideoInfo } from '../../services/sessionVideosApi'
import { canDecode, framesRendered } from './playability'

const FRAME_CHECK_AFTER_SECONDS = 1.5
const MAX_SOURCE_REFRESHES = 3

type Props = { info: SessionVideoInfo; playUrl: string; downloadUrl: string; reportUrl: string; onDownload?: () => void; showFallbackDownload?: boolean }

/** Plays the untouched original; devices that cannot show it get a download. */
export default function SessionVideoPlayer({ info, playUrl, downloadUrl, reportUrl, onDownload, showFallbackDownload = true }: Props) {
  const { t, i18n } = useTranslation()
  const [state, setState] = useState<'checking' | 'playable' | 'unplayable'>('checking')
  const [source, setSource] = useState(playUrl)
  const [ratio,setRatio] = useState((info.width && info.height) ? info.width / info.height : 9 / 16)
  const [rate,setRate] = useState(1)
  const video = useRef<HTMLVideoElement>(null)
  const verified = useRef(false)
  const reported = useRef(false)
  const refreshes = useRef(0)
  const resumeAt = useRef(0)

  const giveUp = (reason: 'unsupported' | 'no_frames' | 'error') => {
    if (!reported.current) { reported.current = true; reportPlaybackIssue(reportUrl, reason) }
    video.current?.pause()
    setState('unplayable')
  }

  useEffect(() => {
    let alive = true
    verified.current = false; reported.current = false; refreshes.current = 0; resumeAt.current = 0
    setSource(playUrl); setState('checking')
    canDecode(info).then(ok => {
      if (!alive) return
      if (ok) setState('playable')
      else { reported.current = true; reportPlaybackIssue(reportUrl, 'unsupported'); setState('unplayable') }
    })
    return () => { alive = false }
  }, [info, playUrl, reportUrl])

  useEffect(() => {
    let alive = true
    if (info.poster_url) {
      const poster = new Image()
      poster.onload = () => { if (alive && poster.naturalHeight) setRatio(poster.naturalWidth / poster.naturalHeight) }
      poster.src = info.poster_url
    }
    return () => { alive = false }
  }, [info.poster_url])
  const frameStyle = { '--session-ratio': ratio } as CSSProperties

  if (state === 'checking') return <div className="session-video-player" style={frameStyle}><div className="session-video-frame" aria-busy="true" /></div>
  if (state === 'unplayable') {
    return <div className="session-video-player" style={frameStyle}><div className="session-video-frame session-video-unplayable" role="status">
      <p>{t('sessionVideo.unplayable')}</p>
      {showFallbackDownload && <a href={downloadUrl || undefined} onClick={onDownload ? e => {e.preventDefault(); onDownload()} : undefined} download={info.filename} className="session-video-download">
        <Download size={18} aria-hidden />{t('sessionVideo.download', { size: formatBytes(info.size_bytes, i18n.language) })}
      </a>}
    </div></div>
  }
  return <div className="session-video-player" style={frameStyle}><div className="session-video-frame">
    <video
      ref={video}
      src={source}
      controls={false}
      playsInline
      poster={info.poster_url}
      preload="none"
      aria-label={t('sessionVideo.videoAria')}
      onLoadedMetadata={event => { const element = event.currentTarget; if (element.videoWidth && element.videoHeight) setRatio(element.videoWidth / element.videoHeight); if (resumeAt.current) event.currentTarget.currentTime = resumeAt.current }}
      onTimeUpdate={event => {
        const element = event.currentTarget
        if (verified.current || element.currentTime < FRAME_CHECK_AFTER_SECONDS) return
        if (framesRendered(element)) verified.current = true
        else giveUp('no_frames')
      }}
      onError={event => {
        const element = event.currentTarget
        const code = element.error?.code
        if (code === 2 && refreshes.current < MAX_SOURCE_REFRESHES) {
          // Network error, e.g. the signed B2 URL expired mid-session: ask
          // for a fresh one and resume where the viewer was.
          refreshes.current += 1
          resumeAt.current = element.currentTime
          setSource(`${playUrl}${playUrl.includes('?') ? '&' : '?'}r=${refreshes.current}`)
          return
        }
        if (code === 3 || code === 4) giveUp(code === 4 ? 'unsupported' : 'error')
        else if (code === 2) giveUp('error') // Refreshes exhausted: report and fall back to download.
      }}
    />
    <ImmersiveControls videoRef={video} playbackRate={rate} onPlaybackRateChange={value=>{setRate(value);if(video.current)video.current.playbackRate=value}} />
  </div></div>
}
