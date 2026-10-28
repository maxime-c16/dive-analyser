import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Download } from 'lucide-react'
import { formatBytes, reportPlaybackIssue, type SessionVideoInfo } from '../../services/sessionVideosApi'
import { canDecode, framesRendered } from './playability'

const FRAME_CHECK_AFTER_SECONDS = 1.5
const MAX_SOURCE_REFRESHES = 3

type Props = { info: SessionVideoInfo; playUrl: string; downloadUrl: string; reportUrl: string }

/** Plays the untouched original; devices that cannot show it get a download. */
export default function SessionVideoPlayer({ info, playUrl, downloadUrl, reportUrl }: Props) {
  const { t, i18n } = useTranslation()
  const [state, setState] = useState<'checking' | 'playable' | 'unplayable'>('checking')
  const [source, setSource] = useState(playUrl)
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

  if (state === 'checking') return <div className="session-video-frame" aria-busy="true" />
  if (state === 'unplayable') {
    return <div className="session-video-frame session-video-unplayable" role="status">
      <p>{t('sessionVideo.unplayable')}</p>
      <a href={downloadUrl} download={info.filename} className="session-video-download">
        <Download size={18} aria-hidden />{t('sessionVideo.download', { size: formatBytes(info.size_bytes, i18n.language) })}
      </a>
    </div>
  }
  return <div className="session-video-frame">
    <video
      ref={video}
      src={source}
      controls
      playsInline
      preload="metadata"
      aria-label={t('sessionVideo.videoAria')}
      onLoadedMetadata={event => { if (resumeAt.current) event.currentTarget.currentTime = resumeAt.current }}
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
      }}
    />
  </div>
}
