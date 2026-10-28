import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import PageLoading from '../components/PageLoading'
import ShareDiveButton from '../components/clip-viewer/ShareDiveButton'
import SessionVideoPlayer from '../components/session-video/SessionVideoPlayer'
import '../components/session-video/sessionVideo.css'
import '../components/clip-viewer/clipViewer.css'
import {
  formatBytes, formatDuration, formatSessionDate, getSessionVideo, listSessionVideos,
  sessionVideoPaths, type SessionVideoInfo,
} from '../services/sessionVideosApi'

function summary(video: SessionVideoInfo, locale: string) {
  return [formatDuration(video.duration_seconds), formatBytes(video.size_bytes, locale)].filter(Boolean).join(' · ')
}

export function SessionVideoList() {
  const { t, i18n } = useTranslation()
  const [items, setItems] = useState<SessionVideoInfo[] | null>(null)
  const [error, setError] = useState(false)
  useEffect(() => {
    let alive = true
    listSessionVideos().then(data => { if (alive) setItems(data) }).catch(() => { if (alive) setError(true) })
    return () => { alive = false }
  }, [])
  if (error) return <p role="alert">{t('sessionVideo.unavailable')}</p>
  if (!items) return <PageLoading message={t('sessionVideo.loading')} />
  return <main className="session-video-page">
    <header><h1>{t('sessionVideo.title')}</h1></header>
    {items.length === 0 ? <p className="text-app-muted">{t('sessionVideo.empty')}</p> : <ul className="grid gap-2">
      {items.map(video => <li key={video.id}>
        <Link to={`/session-videos/${video.id}`} className="touch-target flex items-center justify-between gap-4 border border-app bg-app-panel px-4 py-3">
          <span className="session-video-date font-medium">{formatSessionDate(video, i18n.language)}</span>
          <span className="text-sm text-app-muted">{summary(video, i18n.language)}</span>
        </Link>
      </li>)}
    </ul>}
  </main>
}

export default function SessionVideoPage() {
  const { t, i18n } = useTranslation()
  const { videoId } = useParams()
  const id = Number(videoId)
  const [video, setVideo] = useState<SessionVideoInfo | null>(null)
  const [error, setError] = useState(false)
  useEffect(() => {
    let alive = true
    setVideo(null); setError(false)
    if (!Number.isInteger(id) || id <= 0) { setError(true); return }
    getSessionVideo(id).then(data => { if (alive) setVideo(data) }).catch(() => { if (alive) setError(true) })
    return () => { alive = false }
  }, [id])
  if (error) return <p role="alert">{t('sessionVideo.unavailable')}</p>
  if (!video) return <PageLoading message={t('sessionVideo.loading')} />
  const paths = sessionVideoPaths(video.id)
  return <main className="session-video-page">
    <header>
      <div><h1>{formatSessionDate(video, i18n.language)}</h1><p>{summary(video, i18n.language)}</p></div>
      {video.can_share && <div className="session-video-actions">
        <ShareDiveButton key={video.id} id={video.id} sharesPath={paths.shares} label={t('sessionVideo.share')} />
      </div>}
    </header>
    <SessionVideoPlayer info={video} playUrl={paths.play} downloadUrl={paths.download} reportUrl={paths.report} />
  </main>
}
