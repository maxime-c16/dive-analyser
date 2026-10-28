import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowLeft, Bell, LogIn, ShieldCheck, UserPlus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { api } from '../../services/api'
import { useAuth } from '../../contexts/AuthContext'
import { runSessionMutation } from '../../contexts/sessionMutex'
import './sessionVideo.css'

type Step = 'login' | 'account' | 'club' | 'group' | 'email'
type Group = { id: number; name: string; club_id: number; club: string }
const fieldClass = 'w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text placeholder:text-app-muted focus:outline-none focus:ring-1 focus:ring-app-accent'
const labelClass = 'mb-1 block text-xs font-medium uppercase tracking-wide text-app-muted'
const buttonClass = 'touch-target inline-flex w-full items-center justify-center gap-2 border border-app-strong bg-app-panel px-4 py-2.5 text-sm font-semibold text-app-text disabled:opacity-60'

/** Same panel, controls and spacing as Login/Invite; one decision per screen. */
function AccountPanel({ title, onBack, children }: { title: string; onBack?: () => void; children: ReactNode }) {
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => { heading.current?.focus() }, [title])
  return <main className="session-auth flex items-center justify-center bg-app px-4 py-4">
    <section className="session-auth-panel w-full max-w-sm border border-app bg-app-panel p-8">
      <div className="mb-6 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-app-accent" aria-hidden /><span className="text-lg font-semibold text-app-text">Dive Analyser</span></div>
        {onBack && <button type="button" aria-label="Retour" onClick={onBack} className="touch-target inline-flex items-center justify-center text-app-muted"><ArrowLeft size={20} /></button>}
      </div>
      <h1 ref={heading} tabIndex={-1} className="mb-6 text-xl font-semibold text-app-text focus:outline-none">{title}</h1>
      {children}
    </section>
  </main>
}

export default function SessionOnboarding({ shareId, initialStep, onBack, onComplete }: {
  shareId: string; initialStep: 'account' | 'login'; onBack: () => void; onComplete: (path: string) => void
}) {
  const { t } = useTranslation()
  const { refresh } = useAuth()
  const [step, setStep] = useState<Step>(initialStep)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(true)
  const [groups, setGroups] = useState<Group[]>([])
  const [club, setClub] = useState('')
  const [group, setGroup] = useState('')
  const [emailEnabled, setEmailEnabled] = useState(true)
  const [destination, setDestination] = useState('')
  const [busy, setBusy] = useState(false)
  const [loadingGroups, setLoadingGroups] = useState(true)
  const [error, setError] = useState('')
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  useEffect(() => {
    let live = true
    ;(async () => {
      const all: Group[] = []
      let params: Record<string, string | number> = {}
      for (;;) {
        const { data } = await api.get<{ items: Group[]; next_after: { club: string; group: string; id: number } | null }>(
          `/api/v1/shared-dives/sessions/${shareId}/groups`, { params })
        all.push(...data.items)
        if (!data.next_after) break
        params = { after_club: data.next_after.club, after_group: data.next_after.group, after_id: data.next_after.id }
      }
      if (live) setGroups(all)
    })()
      .catch(() => { if (live) setError('Groupes indisponibles') })
      .finally(() => { if (live) setLoadingGroups(false) })
    return () => { live = false }
  }, [shareId])
  const changeStep = (next: Step) => { setError(''); setStep(next) }
  const alert = error && <p role="alert" className="mb-4 text-sm text-red-400">{error}</p>

  async function login() {
    setBusy(true); setError('')
    try {
      const response = await runSessionMutation(() => fetch('/api/v1/auth/login', {
        method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, remember_me: remember }),
      }))
      if (!response.ok) { if (alive.current) setError(t('login.invalidCredentials')); return }
      // The parent resolves the session link after the normal auth refresh.
      await refresh()
    } catch { if (alive.current) setError(t('login.networkError')) }
    finally { if (alive.current) setBusy(false) }
  }
  async function signup() {
    setBusy(true); setError('')
    try {
      const { data } = await runSessionMutation(() => api.post(`/api/v1/shared-dives/sessions/${shareId}/signup`, {
        display_name: name, email, password, group_id: Number(group), email_enabled: true,
      }))
      if (!alive.current) return
      setPassword(''); setDestination(data.path); changeStep('email')
    } catch { if (alive.current) setError('Inscription impossible. Connectez-vous si vous avez déjà un compte.') }
    finally { if (alive.current) setBusy(false) }
  }

  if (step === 'email') return <AccountPanel title="Les prochaines séances">
    <label className="mb-6 flex cursor-pointer items-center gap-3 select-none">
      <input type="checkbox" className="h-4 w-4 shrink-0 accent-app-accent" checked={emailEnabled} disabled={busy}
        onChange={async event => {
          const enabled = event.target.checked
          setBusy(true); setError('')
          try { await api.put('/api/v1/session-preferences', { enabled }); if (alive.current) setEmailEnabled(enabled) }
          catch { if (alive.current) setError('Préférence non enregistrée') }
          finally { if (alive.current) setBusy(false) }
        }} />
      <span className="text-sm text-app-text">Recevoir un e-mail pour mon groupe</span>
    </label>
    {alert}
    <button className={buttonClass} disabled={busy} onClick={async () => {
      setBusy(true)
      try { await refresh(); onComplete(destination) }
      catch { if (alive.current) { setError('Connexion impossible'); setBusy(false) } }
    }}><Bell size={16} aria-hidden />Ouvrir la séance</button>
  </AccountPanel>

  if (step === 'club') return <AccountPanel title="Mon club" onBack={() => changeStep('account')}>
    <form onSubmit={event => { event.preventDefault(); changeStep('group') }}>
      <select aria-label="Club" className={`${fieldClass} mb-6`} required value={club} disabled={loadingGroups}
        onChange={event => { setClub(event.target.value); setGroup('') }}>
        <option value="">Choisir un club</option>
        {[...new Map(groups.map(item => [item.club_id, item.club])).entries()].map(([id, title]) => <option key={id} value={id}>{title}</option>)}
      </select>
      {alert}
      <button className={buttonClass} disabled={!club || loadingGroups}>Continuer</button>
    </form>
  </AccountPanel>

  if (step === 'group') return <AccountPanel title="Mon groupe" onBack={() => changeStep('club')}>
    <form onSubmit={event => { event.preventDefault(); void signup() }}>
      <select aria-label="Groupe" className={`${fieldClass} mb-6`} required value={group} onChange={event => setGroup(event.target.value)}>
        <option value="">Choisir un groupe</option>
        {groups.filter(item => String(item.club_id) === club).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select>
      {alert}
      <button className={buttonClass} disabled={busy || !group}><UserPlus size={16} aria-hidden />{busy ? 'Création…' : 'Créer mon compte'}</button>
    </form>
  </AccountPanel>

  const isLogin = step === 'login'
  return <AccountPanel title={isLogin ? 'Se connecter' : 'Créer mon compte'} onBack={onBack}>
    <form onSubmit={event => { event.preventDefault(); if (isLogin) void login(); else changeStep('club') }}>
      {!isLogin && <div className="mb-4"><label htmlFor="session-name" className={labelClass}>Nom</label>
        <input id="session-name" className={fieldClass} autoComplete="name" required maxLength={100} value={name} onChange={event => setName(event.target.value)} /></div>}
      <div className="mb-4"><label htmlFor="session-email" className={labelClass}>E-mail</label>
        <input id="session-email" type="email" className={fieldClass} autoComplete="username" placeholder="you@example.com" required value={email} onChange={event => setEmail(event.target.value)} /></div>
      <div className="mb-4"><label htmlFor="session-password" className={labelClass}>Mot de passe</label>
        <input id="session-password" type="password" className={fieldClass} autoComplete={isLogin ? 'current-password' : 'new-password'} placeholder="••••••••••" minLength={isLogin ? 1 : 10} required value={password} onChange={event => setPassword(event.target.value)} /></div>
      {isLogin && <label className="mb-5 flex cursor-pointer items-center gap-2.5 select-none"><input type="checkbox" checked={remember} onChange={event => setRemember(event.target.checked)} className="h-4 w-4 accent-app-accent" /><span className="text-sm text-app-muted">{t('login.staySignedIn')}</span></label>}
      {alert}
      <button className={buttonClass} disabled={busy}>{isLogin && <LogIn size={16} aria-hidden />}{isLogin ? (busy ? t('login.signingIn') : 'Se connecter') : 'Continuer'}</button>
    </form>
    <button type="button" className="touch-target mt-5 block w-full text-center text-sm text-app-accent hover:underline" onClick={() => { setPassword(''); changeStep(isLogin ? 'account' : 'login') }}>{isLogin ? 'Créer un compte' : 'Se connecter'}</button>
  </AccountPanel>
}
