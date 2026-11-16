import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import PageLoading from '../components/PageLoading'
import SessionGallery from '../components/session-video/SessionGallery'
import { getSessionVideo, getTrainingSession, type SharedTrainingSession } from '../services/sessionVideosApi'

export default function SessionVideoPage() {
  const { t } = useTranslation()
  const { sessionId, videoId } = useParams()
  const [session, setSession] = useState<SharedTrainingSession | null>(null)
  const [error, setError] = useState(false)
  const [epoch, reload] = useState(0)
  useEffect(() => {
    let alive = true
    setSession(null); setError(false)
    const load = async () => {
      const routeId = sessionId ?? videoId ?? ''
      if (!/^\d+$/.test(routeId) || !Number.isSafeInteger(Number(routeId)) || Number(routeId) < 1) throw new Error('Invalid session')
      const id = sessionId ? Number(sessionId) : (await getSessionVideo(Number(videoId))).session_id
      if (!id || !Number.isSafeInteger(id) || id < 1) throw new Error('Invalid session')
      return getTrainingSession(id)
    }
    load().then(data => { if (alive) setSession(data) }).catch(() => { if (alive) setError(true) })
    return () => { alive = false }
  }, [sessionId, videoId, epoch])
  if (error) return <section className="session-gallery-error">
    <p role="alert">{t('sessionVideo.unavailable')}</p>
    <button type="button" className="touch-target mt-4 text-app-accent" onClick={() => reload(value => value + 1)}>{t('sessionVideo.retry')}</button>
  </section>
  if (!session) return <PageLoading />
  return <SessionGallery key={session.session_id} session={session} reload={() => reload(value => value + 1)} />
}
