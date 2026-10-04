import React, { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ShieldCheck, UserPlus } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'

export default function Register() {
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState<boolean | null>(null)
  const { refresh } = useAuth()
  const navigate = useNavigate()

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
      setError('Passwords do not match')
      return
    }
    if (password.length < 10) {
      setError('Password must be at least 10 characters')
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
        }),
      })
      if (!res.ok) {
        if (res.status === 403) setError('Invalid invite code')
        else if (res.status === 409) setError('An account with this email already exists')
        else if (res.status === 429) setError('Too many attempts — please try again later')
        else setError('Registration failed — please check your details')
        return
      }
      setPassword('')
      setConfirm('')
      setInviteCode('')
      await refresh()
      navigate('/dives', { replace: true })
    } catch {
      setError('Network error — please try again')
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
          Member account — view public dives and manage your own.
        </p>

        {open === false && (
          <p className="mb-4 border border-amber-700/60 bg-amber-950/20 p-3 text-sm text-amber-100">
            Registration is currently closed. Ask the owner for a current invite code.
          </p>
        )}

        <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-app-muted">
          Email
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
          Display name <span className="normal-case">(optional)</span>
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
          Password <span className="normal-case">(10+ characters)</span>
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
          Confirm password
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
          Invite code
        </label>
        <input
          type="text"
          value={inviteCode}
          onChange={e => setInviteCode(e.target.value)}
          placeholder="Shared by the owner"
          autoComplete="off"
          className="mb-5 w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text placeholder:text-app-muted focus:outline-none focus:ring-1 focus:ring-app-accent"
          required
        />

        {error && (
          <p className="mb-4 text-sm text-red-400">{error}</p>
        )}

        <button
          type="submit"
          disabled={busy || open === false}
          className="touch-target inline-flex w-full items-center justify-center gap-2 border border-app-strong bg-app-panel px-4 py-2.5 text-sm font-semibold text-app-text disabled:opacity-60"
        >
          <UserPlus className="h-4 w-4" />
          {busy ? 'Creating account…' : 'Create member account'}
        </button>

        <p className="mt-5 text-center text-sm text-app-muted">
          Already have an account?{' '}
          <Link to="/login" className="text-app-accent hover:underline">
            Sign in
          </Link>
        </p>
      </form>
    </div>
  )
}
