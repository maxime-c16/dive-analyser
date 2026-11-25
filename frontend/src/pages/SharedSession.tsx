import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Waves } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useParams, useNavigate } from 'react-router-dom'
import PageLoading from '../components/PageLoading'
import SessionGallery, { type DownloadTarget } from '../components/session-video/SessionGallery'
import SessionOnboarding from '../components/session-video/SessionOnboarding'
import { useSessionHistory } from '../components/session-video/useSessionHistory'
import { visitSharedSession, type SharedSessionVideo } from '../services/sessionVideosApi'
import { useAuth } from '../contexts/AuthContext'

type Onboarding = { shareId: string; step: 'account' | 'login'; target: DownloadTarget | 'login' }

export default function SharedSession() {
  const { t } = useTranslation()
  const { shareId } = useParams()
  const history = useSessionHistory()
  const { hash } = history.location
  const navigate = useNavigate()
  const { checking, user } = useAuth()
  const identity = `${shareId}${hash}`
  const [visit, setVisit] = useState<{ identity: string; data?: SharedSessionVideo; error?: 'invalidLink' | 'sessionUnavailable' }>()
  const [restoreFocus, setRestoreFocus] = useState<DownloadTarget | 'login'>()
  const marker = history.location.state?.sessionOnboarding as Onboarding | undefined
  const onboarding = marker?.shareId === shareId ? marker : undefined
  const previousOnboarding = useRef<Onboarding>()
  const loginButton = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (checking) return
    let alive = true
    if (!/^\d+$/.test(shareId ?? '') || !/^[A-Za-z0-9_-]{43}$/.test(hash.slice(1))) {
      setVisit({ identity, error: 'invalidLink' })
      return
    }
    visitSharedSession(shareId!, hash.slice(1)).then(data => {
      if (alive) setVisit({ identity, data })
    }).catch(() => {
      if (alive) setVisit({ identity, error: 'sessionUnavailable' })
    })
    return () => { alive = false }
  }, [checking, hash, identity, shareId])

  const session = visit?.identity === identity ? visit.data : undefined
  const error = visit?.identity === identity ? visit.error : undefined
  const [completed, setCompleted] = useState<{ identity: string; path: string }>()
  const destination = completed?.identity === identity ? completed.path
    : user && session ? `/sessions/shared/${session.session_id}` : undefined
  useEffect(() => {
    if (destination && !history.returnToBase()) navigate(destination, { replace: true })
  }, [destination, history.location.key, navigate])

  useLayoutEffect(() => {
    if (!onboarding && previousOnboarding.current?.shareId === shareId) {
      setRestoreFocus(previousOnboarding.current?.target)
    }
    previousOnboarding.current = onboarding
  }, [onboarding, shareId])
  useLayoutEffect(() => {
    if (restoreFocus === 'login') {
      loginButton.current?.focus({ preventScroll: true })
      setRestoreFocus(undefined)
    }
  }, [restoreFocus])

  function showOnboarding(step: 'account' | 'login', target: Onboarding['target']) {
    history.change({ sessionOnboarding: { shareId, step, target }, sessionDownloadAccess: undefined }, target !== 'login')
  }

  if (error) return <main id="main-content" className="session-auth flex items-center justify-center bg-app px-4"><p role="alert" className="w-full max-w-sm border border-app bg-app-panel p-8 text-app-text">{t(`sessionVideo.${error}`)}</p></main>
  if (!session || user) return <PageLoading />
  return <>
    <main id="main-content" className="shared-session" tabIndex={-1} hidden={!!onboarding}>
      <header className="session-guest-header">
        <span><Waves size={20} aria-hidden />Dive Analyser</span>
        <button ref={loginButton} className="session-login" type="button" onClick={() => showOnboarding('login', 'login')}>{t('sessionVideo.signIn')}</button>
      </header>
      <SessionGallery key={identity} session={session} guest guestBase={`/api/v1/shared-dives/sessions/${shareId}`}
        suspended={!!onboarding} restoreDownloadFocus={restoreFocus === 'login' ? undefined : restoreFocus}
        onDownloadFocusRestored={() => setRestoreFocus(undefined)}
        onSignup={target => showOnboarding('account', target)} onLogin={target => showOnboarding('login', target)} />
    </main>
    {onboarding && <SessionOnboarding key={identity} shareId={shareId!} initialStep={onboarding.step}
      onBack={() => history.close('sessionOnboarding')} onComplete={path => setCompleted({ identity, path })} />}
  </>
}
