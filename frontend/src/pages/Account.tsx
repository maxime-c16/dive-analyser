import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, Globe2, KeyRound, LogOut, ShieldCheck, UserRound } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'

/** Initials for the avatar. Trims and falls back to the email local part. */
export function initials(name: string, fallbackEmail = ''): string {
  const source = name.trim() || fallbackEmail.split('@')[0] || '?'
  const parts = source.split(/\s+/).filter(Boolean)
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

type Prefs = {
  emailNotifications: boolean
  milestoneAlerts: boolean
  weeklyDigest: boolean
}

const PREFS_KEY = 'dive-analyser.prefs.v1'
const DEFAULT_PREFS: Prefs = {
  emailNotifications: true,
  milestoneAlerts: true,
  weeklyDigest: false,
}

function loadPrefs(): Prefs {
  try {
    const raw = localStorage.getItem(PREFS_KEY)
    if (!raw) return DEFAULT_PREFS
    return { ...DEFAULT_PREFS, ...JSON.parse(raw) }
  } catch {
    return DEFAULT_PREFS
  }
}

/**
 * Notification preferences. The backend has no prefs endpoint yet, so these
 * persist per device until one exists.
 */
function usePrefs(): [Prefs, (patch: Partial<Prefs>) => void] {
  const [prefs, setPrefs] = useState<Prefs>(DEFAULT_PREFS)
  useEffect(() => {
    setPrefs(loadPrefs())
  }, [])
  const update = (patch: Partial<Prefs>) => {
    setPrefs(prev => {
      const next = { ...prev, ...patch }
      try {
        localStorage.setItem(PREFS_KEY, JSON.stringify(next))
      } catch {
        // Private browsing etc: prefs simply don't persist.
      }
      return next
    })
  }
  return [prefs, update]
}

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: () => void
  label: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={onChange}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors ${
        checked ? 'border-app-accent bg-app-accent' : 'border-app bg-app-panel-elevated'
      }`}
    >
      <span
        aria-hidden
        className={`inline-block h-4 w-4 rounded-full bg-[var(--app-text)] transition-transform ${
          checked ? 'translate-x-5' : 'translate-x-1'
        }`}
      />
    </button>
  )
}

const inputCls =
  'w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text focus:outline-none focus:ring-1 focus:ring-app-accent'
const labelCls =
  'mb-1 block text-xs font-medium uppercase tracking-wide text-app-muted'

const sections = [
  { id: 'profile', label: 'Profile', icon: UserRound },
  { id: 'notifications', label: 'Notifications', icon: Bell },
  { id: 'fediverse', label: 'Fediverse', icon: Globe2 },
  { id: 'security', label: 'Security', icon: KeyRound },
] as const

type SectionId = (typeof sections)[number]['id']

/**
 * Global fediverse opt-in (Option 1: manual cross-post only, default OFF).
 * Server is the source of truth; turning it ON never publishes history —
 * each public dive still needs its own per-dive opt-in.
 */
function useFediverseEnabled(active: boolean): {
  enabled: boolean
  loaded: boolean
  busy: boolean
  error: string
  setEnabled: (next: boolean) => Promise<void>
} {
  const [enabled, setEnabledState] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!active || loaded) return
    let alive = true
    fetch('/api/v1/fediverse/settings', { credentials: 'same-origin' })
      .then(async res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        if (alive) {
          setEnabledState(!!data.enabled)
          setLoaded(true)
        }
      })
      .catch(() => {
        if (alive) {
          setError('Fediverse settings unavailable. Try again.')
          setLoaded(true)
        }
      })
    return () => {
      alive = false
    }
  }, [active, loaded])
  const setEnabled = async (next: boolean) => {
    setBusy(true)
    setError('')
    try {
      const res = await fetch('/api/v1/fediverse/settings', {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: next }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setEnabledState(!!data.enabled)
    } catch {
      setError('Could not save. Try again.')
    } finally {
      setBusy(false)
    }
  }
  return { enabled, loaded, busy, error, setEnabled }
}

export default function Account() {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()
  const [section, setSection] = useState<SectionId>('profile')
  const [prefs, updatePrefs] = usePrefs()

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  const displayName = user?.display_name ?? user?.email ?? ''
  const isDiver = !user?.is_admin
  const fediverse = useFediverseEnabled(section === 'fediverse')

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

  const notifRows: { key: keyof Prefs; label: string; desc: string }[] = [
    { key: 'emailNotifications', label: 'Email notifications', desc: 'Milestones and shared-dive comments' },
    { key: 'milestoneAlerts', label: 'Milestone alerts', desc: 'Personal bests and streaks' },
    { key: 'weeklyDigest', label: 'Weekly digest', desc: 'Progress summary every Monday' },
  ]

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-5 border-b border-app pb-4">
        <h1 className="text-3xl font-semibold tracking-tight text-app-text">Profile & settings</h1>
        <p className="mt-1 text-sm text-app-muted">
          Signed in as {displayName}
        </p>
      </header>

      <div className="grid gap-5 md:grid-cols-[220px_1fr]">
        <nav aria-label="Profile sections" className="h-fit border border-app bg-app-panel p-2 md:sticky md:top-4">
          {sections.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => setSection(id)}
              aria-current={section === id ? 'true' : undefined}
              className={`touch-target flex w-full items-center gap-3 px-3 text-sm font-medium ${
                section === id
                  ? 'border border-app bg-app-panel-elevated text-app-text'
                  : 'border border-transparent text-app-muted hover:text-app-text'
              }`}
            >
              <Icon className="h-4 w-4" aria-hidden />
              {label}
            </button>
          ))}
          <div className="mt-2 border-t border-app pt-2">
            <button
              type="button"
              onClick={logout}
              className="touch-target flex w-full items-center gap-3 px-3 text-sm text-app-muted hover:text-app-text"
            >
              <LogOut className="h-4 w-4" aria-hidden />
              Sign out
            </button>
          </div>
        </nav>

        <div className="min-w-0">
          {section === 'profile' && (
            <section aria-label="Profile" className="border border-app bg-app-panel p-5">
              <div className="flex items-center gap-4">
                <div
                  aria-hidden
                  className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-app-panel-elevated text-lg font-bold text-app-accent ring-1 ring-app-accent"
                >
                  {initials(displayName, user?.email ?? '')}
                </div>
                <div className="min-w-0">
                  <div className="truncate font-medium text-app-text">{displayName}</div>
                  <div className="truncate text-sm text-app-muted">{user?.email}</div>
                </div>
                <span
                  className={`ml-auto shrink-0 border px-2 py-1 text-xs font-medium ${
                    isDiver ? 'border-app-accent text-app-accent' : 'border-app text-app-muted'
                  }`}
                >
                  {isDiver ? 'Diver' : 'Administrator'}
                </span>
              </div>
              {isDiver && (
                <p className="mt-3 text-sm leading-6 text-app-muted">
                  You can view public dives shared by divers and manage your own dives.
                  Private dives are visible only to their owners. Forgotten passwords need an administrator reset.
                </p>
              )}
              {!isDiver && (
                <p className="mt-3 text-sm leading-6 text-app-muted">
                  <a href="/admin" className="text-app-accent underline underline-offset-2">
                    Manage users in Administration
                  </a>{' '}
                  — create diver and administrator accounts, reset passwords, and manage diver bindings.
                </p>
              )}
              <p className="mt-3 flex items-start gap-2 text-sm leading-6 text-app-muted">
                <ShieldCheck className="mt-1 h-4 w-4 shrink-0 text-app-accent" aria-hidden />
                Profile details are managed by your administrator. To change your display name, ask an admin.
              </p>
            </section>
          )}

          {section === 'notifications' && (
            <section aria-label="Notifications" className="border border-app bg-app-panel p-5">
              <h2 className="font-semibold text-app-text">Notifications</h2>
              <p className="mt-1 text-sm text-app-muted">Stored on this device until account sync lands.</p>
              <div className="mt-3 divide-y divide-[var(--app-border)]">
                {notifRows.map(row => (
                  <div key={row.key} className="flex items-center justify-between gap-4 py-3">
                    <div>
                      <div className="text-sm font-medium text-app-text">{row.label}</div>
                      <div className="text-xs text-app-muted">{row.desc}</div>
                    </div>
                    <Toggle
                      checked={prefs[row.key]}
                      onChange={() => updatePrefs({ [row.key]: !prefs[row.key] })}
                      label={row.label}
                    />
                  </div>
                ))}
              </div>
            </section>
          )}

          {section === 'fediverse' && (
            <section aria-label="Fediverse" className="border border-app bg-app-panel p-5">
              <h2 className="font-semibold text-app-text">Fediverse sharing</h2>
              <p className="mt-1 text-sm text-app-muted">
                Manual cross-posts to open social apps (Mastodon, Pixelfed). Off by default.
              </p>

              <div
                role="note"
                aria-label="Turning on does not publish existing dives"
                className="mt-3 w-full rounded border border-amber-300/40 bg-amber-300/10 p-3 text-sm leading-6 text-amber-100"
              >
                <strong className="font-semibold">Turning this on does not publish anything yet.</strong>{' '}
                Your existing public dives stay local. Each dive needs its own opt-in afterwards, and only{' '}
                <strong className="font-semibold">public</strong> dives can be federated — private dives are
                never eligible. Cross-posts share <strong className="font-semibold">poster + caption + link only</strong>;
                the original video is never attached.
              </div>

              <div className="mt-3 flex items-center justify-between gap-4 py-2">
                <div className="min-w-0">
                  <div className="text-sm font-medium text-app-text">Fediverse sharing</div>
                  <div className="text-xs text-app-muted">
                    {fediverse.loaded
                      ? fediverse.enabled
                        ? 'On — you can opt in public dives one by one.'
                        : 'Off — no dive can be cross-posted.'
                      : 'Loading…'}
                  </div>
                </div>
                <Toggle
                  checked={fediverse.enabled}
                  onChange={() => void fediverse.setEnabled(!fediverse.enabled)}
                  label="Fediverse sharing"
                />
              </div>
              {fediverse.busy && (
                <p role="status" className="text-xs text-app-muted">
                  Saving…
                </p>
              )}
              {fediverse.error && (
                <p role="alert" className="mt-1 text-sm text-red-400">
                  {fediverse.error}
                </p>
              )}

              <ul className="mt-3 list-disc space-y-1 pl-5 text-sm leading-6 text-app-muted">
                <li>Step 1: turn this on. Nothing is published.</li>
                <li>Step 2: open a public dive → turn on “Fediverse cross-post” for that dive.</li>
                <li>Step 3: use “Copy cross-post text”, paste your dive link from Share, then post it yourself.</li>
              </ul>
              <p className="mt-3 text-xs leading-5 text-app-muted">
                Works the same on phones, tablets, and desktop — this warning is always shown, with no
                hover-only steps.
              </p>
            </section>
          )}

          {section === 'security' && (
            <section aria-label="Security" className="space-y-4">
              <div className="border border-app bg-app-panel p-5">
                <h2 className="flex items-center gap-2 font-semibold text-app-text">
                  <KeyRound className="h-4 w-4 text-app-accent" aria-hidden />
                  Change password
                </h2>
                <form onSubmit={changePassword} className="mt-4 space-y-4">
                  <div>
                    <label className={labelCls} htmlFor="account-current-password">
                      Current password
                    </label>
                    <input
                      id="account-current-password"
                      type="password"
                      value={currentPassword}
                      onChange={e => setCurrentPassword(e.target.value)}
                      autoComplete="current-password"
                      className={inputCls}
                      required
                    />
                  </div>
                  <div>
                    <label className={labelCls} htmlFor="account-new-password">
                      New password <span className="normal-case">(10+ characters)</span>
                    </label>
                    <input
                      id="account-new-password"
                      type="password"
                      value={newPassword}
                      onChange={e => setNewPassword(e.target.value)}
                      autoComplete="new-password"
                      minLength={10}
                      className={inputCls}
                      required
                    />
                  </div>
                  <div>
                    <label className={labelCls} htmlFor="account-confirm-password">
                      Confirm new password
                    </label>
                    <input
                      id="account-confirm-password"
                      type="password"
                      value={confirm}
                      onChange={e => setConfirm(e.target.value)}
                      autoComplete="new-password"
                      className={inputCls}
                      required
                    />
                  </div>
                  {message && (
                    <p role={message.kind === 'error' ? 'alert' : 'status'} className={`text-sm ${message.kind === 'ok' ? 'text-app-accent' : 'text-red-400'}`}>
                      {message.text}
                    </p>
                  )}
                  <button
                    type="submit"
                    disabled={busy}
                    className="touch-target inline-flex items-center justify-center gap-2 border border-app-strong bg-app-panel px-4 py-2.5 text-sm font-semibold text-app-text disabled:opacity-60"
                  >
                    <KeyRound className="h-4 w-4" aria-hidden />
                    {busy ? 'Changing…' : 'Change password'}
                  </button>
                </form>
              </div>

              <div className="border border-app bg-app-panel p-5">
                <h2 className="font-semibold text-app-text">Sessions</h2>
                <p className="mt-1 text-sm text-app-muted">This session ends when you sign out.</p>
                <button
                  type="button"
                  onClick={logout}
                  className="touch-target mt-3 inline-flex items-center justify-center gap-2 border border-app bg-app-panel-elevated px-4 py-2.5 text-sm font-medium text-app-text"
                >
                  <LogOut className="h-4 w-4" aria-hidden />
                  Sign out
                </button>
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  )
}
