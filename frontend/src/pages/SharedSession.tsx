import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation, useParams } from 'react-router-dom'
import PageLoading from '../components/PageLoading'
import SessionVideoPlayer from '../components/session-video/SessionVideoPlayer'
import '../components/session-video/sessionVideo.css'
import {
  formatBytes, formatDuration, formatSessionDate, visitSharedSession, type SharedSessionVideo,
} from '../services/sessionVideosApi'

/** Account-free session page opened from a guest link (secret in the fragment). */
export default function SharedSession() {
  const { t, i18n } = useTranslation()
  const { shareId } = useParams()
  const { hash } = useLocation()
  const [video, setVideo] = useState<SharedSessionVideo | null>(null)
  const [error, setError] = useState<'' | 'invalid' | 'unavailable'>('')
  const [epoch, setEpoch] = useState(0)
  useEffect(() => {
    let alive = true
    setVideo(null); setError('')
    const token = hash.slice(1)
    if (!/^\d+$/.test(shareId ?? '') || !/^[A-Za-z0-9_-]{43}$/.test(token)) { setError('invalid'); return }
    visitSharedSession(shareId!, token)
      .then(data => { if (alive) setVideo(data) })
      .catch(() => { if (alive) setError('unavailable') })
    return () => { alive = false }
  }, [shareId, hash, epoch])
  useEffect(() => {
    const meta = document.createElement('meta')
    meta.name = 'referrer'; meta.content = 'no-referrer'
    document.head.appendChild(meta)
    return () => { meta.remove() }
  }, [])
  if (error) return <main className="shared-session">
    <p role="alert">{t(error === 'invalid' ? 'sessionVideo.invalidLink' : 'sessionVideo.unavailable')}</p>
    {error === 'unavailable' && <button className="mx-4" onClick={() => setEpoch(value => value + 1)}>{t('common.retry')}</button>}
  </main>
  if (!video) return <main className="shared-session"><PageLoading message={t('sessionVideo.loading')} /></main>
  const details = [formatDuration(video.duration_seconds), formatBytes(video.size_bytes, i18n.language)].filter(Boolean).join(' · ')
  return <main className="shared-session">
    <header><h1>{formatSessionDate(video, i18n.language)}</h1><p>{details}</p></header>
    <SessionVideoPlayer info={video} playUrl={video.video_url} downloadUrl={video.download_url}
      reportUrl={`/api/v1/shared-dives/sessions/${shareId}/playback-issues`} />
  </main>
}
