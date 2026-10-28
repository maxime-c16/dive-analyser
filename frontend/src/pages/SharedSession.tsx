import { useEffect, useState } from 'react'
import { useLocation, useParams, useNavigate } from 'react-router-dom'
import PageLoading from '../components/PageLoading'
import SessionGallery from '../components/session-video/SessionGallery'
import SessionOnboarding from '../components/session-video/SessionOnboarding'
import { visitSharedSession, type SharedSessionVideo } from '../services/sessionVideosApi'
import { useAuth } from '../contexts/AuthContext'

export default function SharedSession() {
  const { shareId } = useParams()
  const { hash } = useLocation()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [session, setSession] = useState<SharedSessionVideo | null>(null)
  const [error, setError] = useState('')
  const [onboarding, setOnboarding] = useState<'account' | 'login' | null>(null)
  useEffect(() => {
    let alive = true
    setSession(null); setError(''); setOnboarding(null)
    if (!/^\d+$/.test(shareId ?? '') || !/^[A-Za-z0-9_-]{43}$/.test(hash.slice(1))) {
      setError('Lien invalide'); return
    }
    visitSharedSession(shareId!, hash.slice(1)).then(data => {
      if (!alive) return
      setSession(data)
      if (user) navigate(`/sessions/shared/${data.session_id}`, { replace: true })
    }).catch(() => { if (alive) setError('Séance indisponible') })
    return () => { alive = false }
  }, [shareId, hash, user, navigate])

  if (error) return <main className="session-auth flex items-center justify-center bg-app px-4"><p role="alert" className="w-full max-w-sm border border-app bg-app-panel p-8 text-app-text">{error}</p></main>
  if (!session) return <PageLoading />
  if (onboarding) return <SessionOnboarding key={`${shareId}${hash}`} shareId={shareId!} initialStep={onboarding}
    onBack={() => setOnboarding(null)} onComplete={path => navigate(path, { replace: true })} />
  return <div className="shared-session">
    <SessionGallery session={session} guest guestBase={`/api/v1/shared-dives/sessions/${shareId}`} onSignup={() => setOnboarding('account')} />
    <button className="session-login text-app-accent" onClick={() => setOnboarding('login')}>Se connecter</button>
  </div>
}
