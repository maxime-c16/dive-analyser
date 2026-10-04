import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { KeyRound, LogOut, User } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'

export default function Account() {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  const changePassword = async (e: React.FormEvent) => {
    e.preventDefault()
    setMessage(null)
    if (newPassword !== confirm) {
      setMessage({ kind: 'error', text: 'New passwords do not match' })
      return
    }
    if (newPassword.length < 10) {
      setMessage({ kind: 'error', text: 'New password must be at least 10 characters' })
      return
    }
    setBusy(true)
    try {
      const res = await fetch('/api/v1/auth/change-password', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      })
      if (!res.ok) {
        setMessage({
          kind: 'error',
          text: res.status === 401 ? 'Current password is incorrect' : 'Password change failed — please try again',
        })
        return
      }
      setCurrentPassword('')
      setNewPassword('')
      setConfirm('')
      setMessage({ kind: 'ok', text: 'Password changed. Other sessions were signed out.' })
    } catch {
      setMessage({ kind: 'error', text: 'Network error — please try again' })
    } finally {
      setBusy(false)
    }
  }

  const logout = async () => {
    await signOut()
    navigate('/login', { replace: true })
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <header className="border-b border-app pb-5">
        <h1 className="text-3xl font-semibold tracking-tight text-app-text">Account</h1>
        <p className="mt-2 text-sm text-app-muted">
          Signed in as {user?.display_name ?? user?.email}
        </p>
      </header>

      <section className="border border-app bg-app-panel p-5">
        <div className="flex items-center gap-3">
          <User className="h-5 w-5 text-app-accent" />
          <div>
            <div className="font-medium text-app-text">{user?.display_name}</div>
            <div className="text-sm text-app-muted">{user?.email}</div>
          </div>
          <span
            className={`ml-auto border px-2 py-1 text-xs font-medium ${
              user?.role === 'friend'
                ? 'border-app-accent text-app-accent'
                : 'border-app text-app-muted'
            }`}
          >
            {user?.role === 'friend' ? 'Friend · read-only' : 'Owner'}
          </span>
        </div>
        {user?.role === 'friend' && (
          <p className="mt-3 text-sm leading-6 text-app-muted">
            Friend accounts can view every diver's dives and videos but cannot
            change anything. Forgotten passwords need an owner reset.
          </p>
        )}
      </section>

      <section className="border border-app bg-app-panel p-5">
        <h2 className="flex items-center gap-2 font-semibold text-app-text">
          <KeyRound className="h-4 w-4 text-app-accent" />
          Change password
        </h2>
        <form onSubmit={changePassword} className="mt-4 space-y-4">
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-app-muted">
              Current password
            </label>
            <input
              type="password"
              value={currentPassword}
              onChange={e => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
              className="w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text focus:outline-none focus:ring-1 focus:ring-app-accent"
              required
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-app-muted">
              New password <span className="normal-case">(10+ characters)</span>
            </label>
            <input
              type="password"
              value={newPassword}
              onChange={e => setNewPassword(e.target.value)}
              autoComplete="new-password"
              minLength={10}
              className="w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text focus:outline-none focus:ring-1 focus:ring-app-accent"
              required
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-app-muted">
              Confirm new password
            </label>
            <input
              type="password"
              value={confirm}
              onChange={e => setConfirm(e.target.value)}
              autoComplete="new-password"
              className="w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text focus:outline-none focus:ring-1 focus:ring-app-accent"
              required
            />
          </div>
          {message && (
            <p className={`text-sm ${message.kind === 'ok' ? 'text-app-accent' : 'text-red-400'}`}>
              {message.text}
            </p>
          )}
          <button
            type="submit"
            disabled={busy}
            className="touch-target inline-flex items-center justify-center gap-2 border border-app-strong bg-app-panel px-4 py-2.5 text-sm font-semibold text-app-text disabled:opacity-60"
          >
            <KeyRound className="h-4 w-4" />
            {busy ? 'Changing…' : 'Change password'}
          </button>
        </form>
      </section>

      <section className="border border-app bg-app-panel p-5">
        <button
          type="button"
          onClick={logout}
          className="touch-target inline-flex items-center justify-center gap-2 border border-app bg-app-panel-elevated px-4 py-2.5 text-sm font-medium text-app-text"
        >
          <LogOut className="h-4 w-4" />
          Sign out
        </button>
      </section>
    </div>
  )
}
