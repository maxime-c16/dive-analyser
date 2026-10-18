import React, { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ShieldCheck, UserPlus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../contexts/AuthContext'
import SignupClubSelect from '../components/SignupClubSelect'

export default function Register() {
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [clubId, setClubId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState<boolean | null>(null)
  const { refresh } = useAuth()
  const navigate = useNavigate()
  const { t } = useTranslation()

  useEffect(() => {
    fetch('/api/v1/auth/registration-status', { credentials: 'same-origin' })
      .then((res) => (res.ok ? res.json() : { registration_enabled: false }))
      .then((data) => setOpen(Boolean(data.registration_enabled)))
      .catch(() => setOpen(false))
  }, [])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (password !== confirm) {
      setError(t('register.errorMismatch'))
      return
    }
    if (password.length < 10) {
      setError(t('register.errorTooShort'))
      return
    }
    setBusy(true)
    try {
      const res = await fetch('/api/v1/auth/register', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email,
          password,
          display_name: displayName || undefined,
          invite_code: inviteCode,
          ...(clubId !== null ? { club_id: clubId } : {}),
        }),
      })
      if (!res.ok) {
        if (res.status === 403) setError(t('register.errorInvite'))
        else if (res.status === 409) setError(t('register.errorExists'))
        else if (res.status === 429) setError(t('register.errorTooMany'))
        else if (res.status === 422 && (await res.json().catch(() => null))?.detail?.code === 'club_unavailable') setError(t('register.errorClub'))
        else setError(t('register.errorFailed'))
        return
      }
      setPassword('')
      setConfirm('')
      setInviteCode('')
      await refresh()
      navigate('/dives', { replace: true })
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
        <div className="mb-2 flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-app-accent" />
          <span className="text-lg font-semibold text-app-text">Dive Analyser</span>
        </div>
        <p className="mb-6 text-sm text-app-muted">
          {t('register.subtitle')}
        </p>

        {open === false && (
          <p className="mb-4 border border-amber-700/60 bg-amber-950/20 p-3 text-sm text-amber-100">
            {t('register.closed')}
          </p>
        )}

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
          {t('register.displayName')} <span className="normal-case">({t('common.optional')})</span>
        </label>
        <input
          type="text"
          value={displayName}
          onChange={e => setDisplayName(e.target.value)}
          placeholder="Alex"
          autoComplete="nickname"
          maxLength={120}
          className="mb-4 w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text placeholder:text-app-muted focus:outline-none focus:ring-1 focus:ring-app-accent"
        />

        <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-app-muted">
          {t('login.password')} <span className="normal-case">(10+ {t('common.characters')})</span>
        </label>
        <input
          type="password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          placeholder="••••••••••"
          autoComplete="new-password"
          minLength={10}
          className="mb-4 w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text placeholder:text-app-muted focus:outline-none focus:ring-1 focus:ring-app-accent"
          required
        />

        <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-app-muted">
          {t('register.confirmPassword')}
        </label>
        <input
          type="password"
          value={confirm}
          onChange={e => setConfirm(e.target.value)}
          placeholder="••••••••••"
          autoComplete="new-password"
          className="mb-4 w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text placeholder:text-app-muted focus:outline-none focus:ring-1 focus:ring-app-accent"
          required
        />

        <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-app-muted">
          {t('register.inviteCode')}
        </label>
        <input
          type="text"
          value={inviteCode}
          onChange={e => setInviteCode(e.target.value)}
          placeholder={t('register.invitePlaceholder')}
          autoComplete="off"
          className="mb-5 w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text placeholder:text-app-muted focus:outline-none focus:ring-1 focus:ring-app-accent"
          required
        />

        <SignupClubSelect id="register-club" value={clubId} onChange={setClubId} />

        {error && (
          <p className="mb-4 text-sm text-red-400">{error}</p>
        )}

        <button
          type="submit"
          disabled={busy || open === false}
          className="touch-target inline-flex w-full items-center justify-center gap-2 border border-app-strong bg-app-panel px-4 py-2.5 text-sm font-semibold text-app-text disabled:opacity-60"
        >
          <UserPlus className="h-4 w-4" />
          {busy ? t('register.creating') : t('register.submit')}
        </button>

        <p className="mt-5 text-center text-sm text-app-muted">
          {t('register.alreadyHaveAccount')}{' '}
          <Link to="/login" className="text-app-accent hover:underline">
            {t('login.submit')}
          </Link>
        </p>
      </form>
    </div>
  )
}
