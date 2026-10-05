import React, { useEffect, useState } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import { LogIn, ShieldCheck } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../contexts/AuthContext'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [rememberMe, setRememberMe] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [registrationOpen, setRegistrationOpen] = useState(false)
  const { refresh } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const { t } = useTranslation()
  const from = (location.state as { from?: string })?.from ?? '/'

  useEffect(() => {
    fetch('/api/v1/auth/registration-status', { credentials: 'same-origin' })
      .then((res) => (res.ok ? res.json() : { registration_enabled: false }))
      .then((data) => setRegistrationOpen(Boolean(data.registration_enabled)))
      .catch(() => setRegistrationOpen(false))
  }, [])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const res = await fetch('/api/v1/auth/login', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, remember_me: rememberMe }),
      })
      if (!res.ok) {
        setError(t('login.invalidCredentials'))
        return
      }
      setPassword('')
      await refresh()
      navigate(from, { replace: true })
    } catch {
      setError(t('login.networkError'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-app px-4">
      <form
        onSubmit={submit}
        className="w-full max-w-sm border border-app bg-app-panel p-8"
      >
        <div className="mb-6 flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-app-accent" />
          <span className="text-lg font-semibold text-app-text">Dive Analyser</span>
        </div>

        <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-app-muted">
          {t('login.email')}
        </label>
        <input
          type="email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          placeholder="you@example.com"
          autoComplete="username"
          className="mb-4 w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text placeholder:text-app-muted focus:outline-none focus:ring-1 focus:ring-app-accent"
          required
        />

        <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-app-muted">
          {t('login.password')}
        </label>
        <input
          type="password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          placeholder="••••••••"
          autoComplete="current-password"
          className="mb-4 w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text placeholder:text-app-muted focus:outline-none focus:ring-1 focus:ring-app-accent"
          required
        />

        <label className="mb-5 flex cursor-pointer items-center gap-2.5 select-none">
          <input
            type="checkbox"
            checked={rememberMe}
            onChange={e => setRememberMe(e.target.checked)}
            className="h-4 w-4 rounded-sm border border-app-strong bg-app-panel-elevated accent-app-accent"
          />
          <span className="text-sm text-app-muted">{t('login.staySignedIn')}</span>
        </label>

        {error && (
          <p className="mb-4 text-sm text-red-400">{error}</p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="touch-target inline-flex w-full items-center justify-center gap-2 border border-app-strong bg-app-panel px-4 py-2.5 text-sm font-semibold text-app-text disabled:opacity-60"
        >
          <LogIn className="h-4 w-4" />
          {busy ? t('login.signingIn') : t('login.submit')}
        </button>

        {registrationOpen && (
          <p className="mt-5 text-center text-sm text-app-muted">
            {t('login.newHere')}{' '}
            <Link to="/register" className="text-app-accent hover:underline">
              {t('login.createDiverAccount')}
            </Link>
          </p>
        )}
      </form>
    </div>
  )
}
