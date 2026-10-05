import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, Globe, KeyRound, LogOut, ShieldCheck, UserRound } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../contexts/AuthContext'
import { LANGUAGES, useLang } from '../i18n/I18nProvider'
import type { LanguageCode } from '../i18n/prefs'

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
 * persist per device until one exists. Language rides in the same blob
 * (see i18n/prefs.ts) but applies through I18nProvider.
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
  { id: 'profile', labelKey: 'account.sections.profile', icon: UserRound },
  { id: 'notifications', labelKey: 'account.notifications', icon: Bell },
  { id: 'security', labelKey: 'account.security', icon: KeyRound },
] as const

type SectionId = (typeof sections)[number]['id']

function LanguageSection() {
  const { t } = useTranslation()
  const { language, setLanguage } = useLang()
  return (
    <section aria-label={t('settings.language')} className="border border-app bg-app-panel p-5">
      <h2 className="flex items-center gap-2 font-semibold text-app-text">
        <Globe className="h-4 w-4 text-app-accent" aria-hidden />
        {t('settings.language')}
      </h2>
      <p className="mt-1 text-sm text-app-muted">{t('settings.languageDesc')}</p>
      <div className="mt-3 flex flex-wrap gap-2" role="radiogroup" aria-label={t('settings.language')}>
        {LANGUAGES.map(option => {
          const selected = language === option.value
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => setLanguage(option.value as LanguageCode)}
              className={`touch-target border px-3 py-2 text-sm font-medium transition-colors ${
                selected
                  ? 'border-app-accent bg-app-accent/10 text-app-accent'
                  : 'border-app bg-app-panel-elevated text-app-muted hover:text-app-text'
              }`}
            >
              {option.labelKey ? t(option.labelKey) : option.label}
            </button>
          )
        })}
      </div>
    </section>
  )
}

export default function Account() {
  const { user, signOut } = useAuth()
  const { t } = useTranslation()
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

  const changePassword = async (e: React.FormEvent) => {
    e.preventDefault()
    setMessage(null)
    if (newPassword !== confirm) {
      setMessage({ kind: 'error', text: t('account.errorMismatch') })
      return
    }
    if (newPassword.length < 10) {
      setMessage({ kind: 'error', text: t('account.errorTooShort') })
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
          text: res.status === 401 ? t('account.errorWrongPassword') : t('account.errorChangeFailed'),
        })
        return
      }
      setCurrentPassword('')
      setNewPassword('')
      setConfirm('')
      setMessage({ kind: 'ok', text: t('account.passwordChanged') })
    } catch {
      setMessage({ kind: 'error', text: t('account.errorNetwork') })
    } finally {
      setBusy(false)
    }
  }

  const logout = async () => {
    await signOut()
    navigate('/login', { replace: true })
  }

  const notifRows: { key: keyof Prefs; label: string; desc: string }[] = [
    { key: 'emailNotifications', label: t('account.notifEmail'), desc: t('account.notifEmailDesc') },
    { key: 'milestoneAlerts', label: t('account.notifMilestones'), desc: t('account.notifMilestonesDesc') },
    { key: 'weeklyDigest', label: t('account.notifDigest'), desc: t('account.notifDigestDesc') },
  ]

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-5 border-b border-app pb-4">
        <h1 className="text-3xl font-semibold tracking-tight text-app-text">{t('account.title')}</h1>
        <p className="mt-1 text-sm text-app-muted">
          {t('account.signedInAs')} {displayName}
        </p>
      </header>

      <div className="grid gap-5 md:grid-cols-[220px_1fr]">
        <nav aria-label={t('account.sectionsAria')} className="h-fit border border-app bg-app-panel p-2 md:sticky md:top-4">
          {sections.map((item: { id: SectionId; labelKey: string; icon: React.ComponentType<{ className?: string }> }) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setSection(item.id)}
              aria-current={section === item.id ? 'true' : undefined}
              className={`touch-target flex w-full items-center gap-3 px-3 text-sm font-medium ${
                section === item.id
                  ? 'border border-app bg-app-panel-elevated text-app-text'
                  : 'border border-transparent text-app-muted hover:text-app-text'
              }`}
            >
              <item.icon className="h-4 w-4" aria-hidden />
              {t(item.labelKey)}
            </button>
          ))}
          <div className="mt-2 border-t border-app pt-2">
            <button
              type="button"
              onClick={logout}
              className="touch-target flex w-full items-center gap-3 px-3 text-sm text-app-muted hover:text-app-text"
            >
              <LogOut className="h-4 w-4" aria-hidden />
              {t('account.signOut')}
            </button>
          </div>
        </nav>

        <div className="min-w-0">
          <LanguageSection />

          {section === 'profile' && (
            <section aria-label={t('account.profileAria')} className="border border-app bg-app-panel p-5">
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
                  {isDiver ? t('roles.Diver') : t('roles.Administrator')}
                </span>
              </div>
              {isDiver && (
                <p className="mt-3 text-sm leading-6 text-app-muted">
                  {t('account.diverHint')}
                </p>
              )}
              {!isDiver && (
                <p className="mt-3 text-sm leading-6 text-app-muted">
                  <a href="/admin" className="text-app-accent underline underline-offset-2">
                    {t('account.adminHintLink')}
                  </a>
                  {t('account.adminHint')}
                </p>
              )}
              <p className="mt-3 flex items-start gap-2 text-sm leading-6 text-app-muted">
                <ShieldCheck className="mt-1 h-4 w-4 shrink-0 text-app-accent" aria-hidden />
                {t('account.managedByAdmin')}
              </p>
            </section>
          )}

          {section === 'notifications' && (
            <section aria-label={t('account.notificationsAria')} className="border border-app bg-app-panel p-5">
              <h2 className="font-semibold text-app-text">{t('account.notifications')}</h2>
              <p className="mt-1 text-sm text-app-muted">{t('account.notificationsStored')}</p>
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

          {section === 'security' && (
            <section aria-label={t('account.securityAria')} className="space-y-4">
              <div className="border border-app bg-app-panel p-5">
                <h2 className="flex items-center gap-2 font-semibold text-app-text">
                  <KeyRound className="h-4 w-4 text-app-accent" aria-hidden />
                  {t('account.changePassword')}
                </h2>
                <form onSubmit={changePassword} className="mt-4 space-y-4">
                  <div>
                    <label className={labelCls} htmlFor="account-current-password">
                      {t('account.currentPassword')}
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
                      {t('account.newPassword')} <span className="normal-case">{t('account.newPasswordHint')}</span>
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
                      {t('account.confirmNewPassword')}
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
                    {busy ? t('account.changing') : t('account.changePassword')}
                  </button>
                </form>
              </div>

              <div className="border border-app bg-app-panel p-5">
                <h2 className="font-semibold text-app-text">{t('account.sessions')}</h2>
                <p className="mt-1 text-sm text-app-muted">{t('account.sessionsHint')}</p>
                <button
                  type="button"
                  onClick={logout}
                  className="touch-target mt-3 inline-flex items-center justify-center gap-2 border border-app bg-app-panel-elevated px-4 py-2.5 text-sm font-medium text-app-text"
                >
                  <LogOut className="h-4 w-4" aria-hidden />
                  {t('account.signOut')}
                </button>
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  )
}
