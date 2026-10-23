import MemberAvatar from '../components/MemberAvatar'
import AvatarManager from '../components/AvatarManager'
import React, { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Bell, Globe, Globe2, History, KeyRound, LogOut, ShieldCheck, UserRound } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../contexts/AuthContext'
import { LANGUAGES, useLang } from '../i18n/I18nProvider'
import type { LanguageCode } from '../i18n/prefs'
import ActivitySection from '../components/activity/ActivitySection'
import PushOptInSection from '../components/PushOptInSection'
import { getDiverScore, type DiverScore } from '../services/activityApi'
import {
  getNotificationPrefs,
  setNotificationPref as putNotificationPref,
} from '../services/notificationsApi'
import { getBatchEmailPref, setBatchEmailPref } from '../services/depositsApi'
import { MobileShellActions } from '../navigation/mobileShellActions'

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
 * Server-backed in-app alert types (PR2). The backend owns defaults and
 * state; localStorage is only a fallback cache when the API is down.
 * Order mirrors the server DEFAULTS map.
 */
export const SERVER_NOTIF_TYPES = [
  'new_video',
  'video_ready',
  'new_comment',
  'comment_reply',
  'direct_message',
  'milestone',
  'sync_error',
  'guest_activity',
  // Calendar alerts: exposed by the server (and shown here) only when the
  // calendar feature is on; defaults mirror the backend CALENDAR_DEFAULTS.
  'calendar_invitation',
  'calendar_change',
  'calendar_reminder',
  'calendar_group_reminder',
  'calendar_follow',
] as const


export type ServerNotifType = (typeof SERVER_NOTIF_TYPES)[number]

export const SERVER_NOTIF_DEFAULTS: Record<ServerNotifType, boolean> = {
  new_video: true,
  video_ready: true,
  new_comment: true,
  comment_reply: true,
  direct_message: true,
  milestone: true,
  sync_error: true,
  guest_activity: false,
  calendar_invitation: true,
  calendar_change: true,
  calendar_reminder: true,
  calendar_group_reminder: false,
  calendar_follow: true,
}

const SERVER_PREFS_CACHE_KEY = 'dive-analyser.notif-prefs.server.v1'

/**
 * Per-account fallback cache. The key includes the user id so an API
 * outage after switching accounts never shows the previous account's
 * settings. The pre-existing global key is intentionally not read: it may
 * hold another account's values, and the server repopulates the per-user
 * entry on the next successful sync.
 */
function serverPrefsCacheKey(userId: number | string | undefined): string {
  return userId == null ? SERVER_PREFS_CACHE_KEY : `${SERVER_PREFS_CACHE_KEY}:${String(userId)}`
}

function loadServerFallback(userId?: number | string): Record<ServerNotifType, boolean> {
  const fallback = { ...SERVER_NOTIF_DEFAULTS }
  try {
    const raw = localStorage.getItem(serverPrefsCacheKey(userId))
    if (raw) return { ...fallback, ...(JSON.parse(raw) as Partial<Record<ServerNotifType, boolean>>) }
    // One-time migration: the old per-device `milestoneAlerts` seeds the
    // server `milestone` type until the server answers.
    const legacyRaw = localStorage.getItem(PREFS_KEY)
    if (legacyRaw) {
      const legacy = JSON.parse(legacyRaw) as Partial<Prefs>
      if (typeof legacy.milestoneAlerts === 'boolean') fallback.milestone = legacy.milestoneAlerts
    }
  } catch {
    // Private browsing etc: defaults simply don't persist.
  }
  return fallback
}

/**
 * Server notification preferences. The server is the source of truth;
 * the local cache (seeded once from the legacy `milestoneAlerts` toggle)
 * only covers API outages. Email and weekly digest stay per-device
 * local-only until a later PR ships their delivery.
 */
function useServerNotifPrefs(active: boolean, userId?: number | string): {
  prefs: Record<ServerNotifType, boolean>
  loaded: boolean
  busy: ServerNotifType | null
  error: string
  setPref: (type: ServerNotifType, next: boolean) => Promise<void>
} {
  const { t } = useTranslation()
  const cacheKey = serverPrefsCacheKey(userId)
  const [prefs, setPrefs] = useState<Record<ServerNotifType, boolean>>(() => loadServerFallback(userId))
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState<ServerNotifType | null>(null)
  const [error, setError] = useState('')
  // Account switch: drop the previous account's prefs and refetch. Without
  // this, `loaded` stays true and user B would keep seeing user A's values.
  useEffect(() => {
    setPrefs(loadServerFallback(userId))
    setLoaded(false)
    // Keyed by the resolved storage key (derived from userId).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cacheKey])
  useEffect(() => {
    if (!active || loaded) return
    let alive = true
    getNotificationPrefs()
      .then(async data => {
        if (!alive) return
        const prefs = data?.prefs ?? {}
        const explicit = Array.isArray(data?.explicit) ? data.explicit : []
        const next = { ...SERVER_NOTIF_DEFAULTS }
        for (const type of SERVER_NOTIF_TYPES) {
          if (typeof prefs[type] === 'boolean') next[type] = prefs[type]
        }
        // One-time push: a legacy per-device `milestoneAlerts` seeds the
        // server `milestone` type only when the server holds no explicit
        // override for it. An explicit server row always wins (it may come
        // from another device), so the legacy value must not overwrite it.
        // The local flag is set after a successful PUT *or* after skipping
        // for an explicit override — in both cases this device must never
        // migrate again. A failed PUT leaves the flag unset to retry next
        // sync. Only the key present in the stored blob counts (not the
        // in-memory default).
        const markMigrated = () => {
          try {
            const rawCurrent = localStorage.getItem(PREFS_KEY)
            const stored = rawCurrent ? (JSON.parse(rawCurrent) as Record<string, unknown>) : {}
            localStorage.setItem(
              PREFS_KEY,
              JSON.stringify({ ...stored, milestoneMigrated: true }),
            )
          } catch {
            // Flag write is best-effort; a miss simply retries next sync.
          }
        }
        try {
          const rawLegacy = localStorage.getItem(PREFS_KEY)
          if (rawLegacy) {
            const parsed = JSON.parse(rawLegacy) as Record<string, unknown>
            if (
              parsed.milestoneMigrated !== true &&
              typeof parsed.milestoneAlerts === 'boolean'
            ) {
              if (explicit.includes('milestone')) {
                markMigrated()
              } else {
                try {
                  const saved = await putNotificationPref(
                    'milestone',
                    parsed.milestoneAlerts,
                  )
                  if (!alive) return
                  next.milestone = !!saved.enabled
                } catch {
                  // PUT failed: keep the server values on screen, leave the
                  // flag unset so the next sync retries.
                  if (!alive) return
                  setPrefs(next)
                  setLoaded(true)
                  try {
                    localStorage.setItem(cacheKey, JSON.stringify(next))
                  } catch {
                    // Cache is best-effort; the server already holds the truth.
                  }
                  return
                }
                markMigrated()
              }
            }
          }
        } catch {
          // Corrupt blob: keep the server values.
        }
        if (!alive) return
        setPrefs(next)
        setLoaded(true)
        try {
          localStorage.setItem(cacheKey, JSON.stringify(next))
        } catch {
          // Cache is best-effort; the server already holds the truth.
        }
      })
      .catch(() => {
        if (!alive) return
        setError(t('account.notifLoadError'))
        setLoaded(true)
      })
    return () => {
      alive = false
    }
  }, [active, loaded, cacheKey, t])
  const setPref = async (type: ServerNotifType, next: boolean) => {
    const previous = prefs[type]
    setPrefs(prev => ({ ...prev, [type]: next }))
    setBusy(type)
    setError('')
    try {
      const saved = await putNotificationPref(type, next)
      const value = !!saved.enabled
      setPrefs(prev => ({ ...prev, [type]: value }))
      try {
        const raw = localStorage.getItem(cacheKey)
        const stored = raw ? (JSON.parse(raw) as Record<string, unknown>) : {}
        localStorage.setItem(cacheKey, JSON.stringify({ ...stored, [type]: value }))
      } catch {
        // Cache is best-effort; the server already holds the truth.
      }
    } catch {
      setPrefs(prev => ({ ...prev, [type]: previous }))
      setError(t('account.notifSaveError'))
    } finally {
      setBusy(null)
    }
  }
  return { prefs, loaded, busy, error, setPref }
}

/**
 * Notification preferences. Email and weekly digest have no delivery
 * endpoint yet, so they persist per device (see i18n/prefs.ts for the
 * shared blob). In-app alert types live on the server instead.
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
        // Merge into the stored blob, not `next`: language (and any future
        // field written by another surface) must survive a notification
        // toggle.
        const raw = localStorage.getItem(PREFS_KEY)
        const stored = raw ? (JSON.parse(raw) as Record<string, unknown>) : {}
        localStorage.setItem(PREFS_KEY, JSON.stringify({ ...stored, ...next }))
      } catch {
        // Private browsing etc: prefs simply don't persist.
      }
      return next
    })
  }
  return [prefs, update]
}

/**
 * Server-backed batch-email opt-out ("Récupérer mes plongeons" mail).
 * Independent from the per-device email toggle below: this one actually
 * stops the server from sending deposit-batch emails.
 */
function BatchEmailToggle() {
  const { t } = useTranslation()
  const [enabled, setEnabled] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let live = true
    getBatchEmailPref()
      .then((value) => {
        if (live) {
          setEnabled(value)
          setLoaded(true)
        }
      })
      .catch(() => {
        if (live) setLoaded(true)
      })
    return () => {
      live = false
    }
  }, [])
  const toggle = async () => {
    setBusy(true)
    try {
      setEnabled(await setBatchEmailPref(!enabled))
    } catch {
      // Keep the previous state; the row below explains the failure path.
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex items-center justify-between gap-4 py-3">
      <div>
        <div className="text-sm font-medium text-app-text">{t('deposits.emailToggle')}</div>
        <div className="text-xs text-app-muted">{t('deposits.emailToggleDesc')}</div>
      </div>
      <Toggle
        checked={enabled}
        onChange={() => void toggle()}
        label={t('deposits.emailToggle')}
        disabled={!loaded || busy}
      />
    </div>
  )
}

function Toggle({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean
  onChange: () => void
  label: string
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      aria-disabled={disabled || undefined}
      onClick={onChange}
      disabled={disabled}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
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
  { id: 'activity', labelKey: 'account.sections.activity', icon: History },
  { id: 'notifications', labelKey: 'account.notifications', icon: Bell },
  { id: 'fediverse', labelKey: 'account.fediverse.section', icon: Globe2 },
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

/**
 * Account-aggregate diver score (0-100 composite): performance from received
 * votes (automatic matchmaking + manual jury), judging from dives evaluated,
 * community from likes/comments sent and received. Stays hidden when the API
 * is unreachable or returns an unexpected shape.
 */
function DiverScoreSection() {
  const { t } = useTranslation()
  const [score, setScore] = useState<DiverScore | null>(null)
  const [loaded, setLoaded] = useState(false)
  useEffect(() => {
    let alive = true
    // Deferred so a missing fetch (or any sync throw) becomes a rejection.
    Promise.resolve()
      .then(() => getDiverScore())
      .then(data => {
        if (!alive) return
        if (typeof data?.score === 'number') setScore(data)
        setLoaded(true)
      })
      .catch(() => {
        if (alive) setLoaded(true)
      })
    return () => {
      alive = false
    }
  }, [])
  if (!loaded || !score) return null
  const rows = [
    {
      label: t('account.diverScore.performance', {
        mean: score.performance.mean_score !== null ? score.performance.mean_score.toFixed(1) : '—',
        count: score.performance.rating_count,
      }),
      points: score.performance.points,
      weight: score.performance.weight,
    },
    {
      label: t('account.diverScore.judging', { count: score.judging.evaluated_dives }),
      points: score.judging.points,
      weight: score.judging.weight,
    },
    {
      label: t('account.diverScore.community', { count: score.community.interactions }),
      points: score.community.points,
      weight: score.community.weight,
    },
  ]
  return (
    <section aria-label={t('account.diverScore.title')} className="mt-4 border border-app bg-app-panel-elevated p-5">
      <div className="flex items-baseline gap-3">
        <h2 className="font-semibold text-app-text">{t('account.diverScore.title')}</h2>
        {score.provisional && (
          <span className="border border-app-accent px-2 py-0.5 text-xs font-medium text-app-accent">
            {t('account.diverScore.provisional')}
          </span>
        )}
      </div>
      <p className="mt-1 text-sm text-app-muted">{t('account.diverScore.subtitle')}</p>
      <p className="mt-3 text-4xl font-semibold text-app-accent" aria-live="polite">
        {score.score}
        <span className="text-base font-normal text-app-muted"> / 100</span>
      </p>
      <ul className="mt-4 space-y-3">
        {rows.map(row => (
          <li key={row.label}>
            <div className="flex items-baseline justify-between gap-4 text-sm">
              <span className="text-app-text">{row.label}</span>
              <span className="shrink-0 text-xs text-app-muted">
                {row.points} / {row.weight}
              </span>
            </div>
            <div
              role="progressbar"
              aria-label={row.label}
              aria-valuenow={row.points}
              aria-valuemin={0}
              aria-valuemax={row.weight}
              className="mt-1 h-1.5 w-full bg-app-panel"
            >
              <div
                className="h-full bg-app-accent"
                style={{ width: `${row.weight ? Math.min(100, (row.points / row.weight) * 100) : 0}%` }}
              />
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

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
  const { t } = useTranslation()
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
          setError(t('account.fediverse.errorLoad'))
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
      setError(t('account.fediverse.errorSave'))
    } finally {
      setBusy(false)
    }
  }
  return { enabled, loaded, busy, error, setEnabled }
}

export default function Account() {
  const { user, signOut, refresh } = useAuth()
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
  const fediverse = useFediverseEnabled(section === 'fediverse')
  const serverNotifs = useServerNotifPrefs(section === 'notifications', user?.user_id)

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
    { key: 'weeklyDigest', label: t('account.notifDigest'), desc: t('account.notifDigestDesc') },
  ]

  const serverNotifRows: { type: ServerNotifType; label: string; desc: string }[] = [
    { type: 'new_video', label: t('account.notifNewVideo'), desc: t('account.notifNewVideoDesc') },
    { type: 'video_ready', label: t('account.notifVideoReady'), desc: t('account.notifVideoReadyDesc') },
    { type: 'new_comment', label: t('account.notifNewComment'), desc: t('account.notifNewCommentDesc') },
    { type: 'direct_message', label: t('messages.title'), desc: t('messages.notificationDesc') },
    { type: 'comment_reply', label: t('account.notifCommentReply'), desc: t('account.notifCommentReplyDesc') },
    { type: 'milestone', label: t('account.notifMilestones'), desc: t('account.notifMilestonesDesc') },
    { type: 'sync_error', label: t('account.notifSyncError'), desc: t('account.notifSyncErrorDesc') },
    { type: 'guest_activity', label: t('account.notifGuestActivity'), desc: t('account.notifGuestActivityDesc') },
  ]
  const calendarNotifRows: { type: ServerNotifType; label: string; desc: string }[] =
    user?.features?.calendar === true
      ? [
          { type: 'calendar_invitation', label: t('account.notifCalendarInvitation'), desc: t('account.notifCalendarInvitationDesc') },
          { type: 'calendar_change', label: t('account.notifCalendarChange'), desc: t('account.notifCalendarChangeDesc') },
          { type: 'calendar_reminder', label: t('account.notifCalendarReminder'), desc: t('account.notifCalendarReminderDesc') },
          { type: 'calendar_group_reminder', label: t('account.notifCalendarGroupReminder'), desc: t('account.notifCalendarGroupReminderDesc') },
          { type: 'calendar_follow', label: t('account.notifCalendarFollow'), desc: t('account.notifCalendarFollowDesc') },
        ]
      : []

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-5 border-b border-app pb-4">
        <div className="flex items-center gap-2">
          <h1 className="min-w-0 flex-1 text-3xl font-semibold tracking-tight text-app-text">{t('account.title')}</h1>
          <MobileShellActions />
        </div>
        <p className="mt-1 text-sm text-app-muted">
          {t('account.signedInAs')} {displayName}
        </p>
        {user && <Link to={`/users/${user.user_id}`} className="mt-3 inline-block text-sm text-app-accent hover:underline">{t('community.myProfile')}</Link>}
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
                <MemberAvatar member={user ?? { display_name: displayName }} size={56} />
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
              {user && <AvatarManager member={user} onChange={async () => { await refresh() }} />}
              <DiverScoreSection />
            </section>
          )}

          {section === 'activity' && <ActivitySection />}

          {section === 'notifications' && (
            <section aria-label={t('account.notificationsAria')} className="border border-app bg-app-panel p-5">
              <h2 className="font-semibold text-app-text">{t('account.notifications')}</h2>
              <p className="mt-1 text-sm text-app-muted">{t('account.notificationsStored')}</p>
              <h3 className="mt-4 text-sm font-semibold text-app-text">{t('account.notifInApp')}</h3>
              <p className="mt-1 text-xs text-app-muted">{t('account.notifInAppDesc')}</p>
              {!serverNotifs.loaded && (
                <p role="status" className="mt-2 text-xs text-app-muted">
                  {t('common.loading')}
                </p>
              )}
              {serverNotifs.busy && (
                <p role="status" className="mt-2 text-xs text-app-muted">
                  {t('account.notifSaving')}
                </p>
              )}
              {serverNotifs.error && (
                <p role="alert" className="mt-2 text-sm text-red-400">
                  {serverNotifs.error}
                </p>
              )}
              <div className="mt-1 divide-y divide-[var(--app-border)]">
                {serverNotifRows.map(row => (
                  <div key={row.type} className="flex items-center justify-between gap-4 py-3">
                    <div>
                      <div className="text-sm font-medium text-app-text">{row.label}</div>
                      <div className="text-xs text-app-muted">{row.desc}</div>
                    </div>
                    <Toggle
                      checked={serverNotifs.prefs[row.type]}
                      onChange={() => void serverNotifs.setPref(row.type, !serverNotifs.prefs[row.type])}
                      label={row.label}
                      disabled={!serverNotifs.loaded || serverNotifs.busy === row.type}
                    />
                  </div>
                ))}
              </div>
              {calendarNotifRows.length > 0 && (
                <section aria-labelledby="notif-calendar-heading">
                  <h3 id="notif-calendar-heading" className="mt-4 text-sm font-semibold text-app-text">
                    {t('account.notifCalendarHeading')}
                  </h3>
                  <p className="mt-1 text-xs text-app-muted">{t('account.notifCalendarDesc')}</p>
                  <div className="mt-1 divide-y divide-[var(--app-border)]">
                    {calendarNotifRows.map(row => (
                      <div key={row.type} className="flex items-center justify-between gap-4 py-3">
                        <div>
                          <div className="text-sm font-medium text-app-text">{row.label}</div>
                          <div className="text-xs text-app-muted">{row.desc}</div>
                        </div>
                        <Toggle
                          checked={serverNotifs.prefs[row.type]}
                          onChange={() => void serverNotifs.setPref(row.type, !serverNotifs.prefs[row.type])}
                          label={row.label}
                          disabled={!serverNotifs.loaded || serverNotifs.busy === row.type}
                        />
                      </div>
                    ))}
                  </div>
                </section>
              )}
              <h3 className="mt-4 text-sm font-semibold text-app-text">{t('account.notifOnDevice')}</h3>
              <BatchEmailToggle />
              <PushOptInSection />
              <div className="mt-1 divide-y divide-[var(--app-border)]">
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
            <section aria-label={t('account.fediverse.section')} className="border border-app bg-app-panel p-5">
              <h2 className="font-semibold text-app-text">{t('account.fediverse.heading')}</h2>
              <p className="mt-1 text-sm text-app-muted">
                {t('account.fediverse.description')}
              </p>

              <div
                role="note"
                aria-label={t('account.fediverse.noteAria')}
                className="mt-3 w-full rounded border border-amber-300/40 bg-amber-300/10 p-3 text-sm leading-6 text-amber-100"
              >
                <strong className="font-semibold">{t('account.fediverse.noteStrong')}</strong>{' '}
                {t('account.fediverse.noteLocal')}{' '}
                <strong className="font-semibold">{t('account.fediverse.notePublicWord')}</strong>{' '}
                {t('account.fediverse.noteOptIn')}{' '}
                <strong className="font-semibold">{t('account.fediverse.noteContentWord')}</strong>:
                {t('account.fediverse.noteContent')}{' '}
                {t('account.fediverse.noteAttach')}
              </div>

              <div className="mt-3 flex items-center justify-between gap-4 py-2">
                <div className="min-w-0">
                  <div className="text-sm font-medium text-app-text">{t('account.fediverse.heading')}</div>
                  <div className="text-xs text-app-muted">
                    {fediverse.loaded
                      ? fediverse.enabled
                        ? t('account.fediverse.statusOn')
                        : t('account.fediverse.statusOff')
                      : t('common.loading')}
                  </div>
                </div>
                <Toggle
                  checked={fediverse.enabled}
                  onChange={() => void fediverse.setEnabled(!fediverse.enabled)}
                  label={t('account.fediverse.heading')}
                />
              </div>
              {fediverse.busy && (
                <p role="status" className="text-xs text-app-muted">
                  {t('account.fediverse.saving')}
                </p>
              )}
              {fediverse.error && (
                <p role="alert" className="mt-1 text-sm text-red-400">
                  {fediverse.error}
                </p>
              )}

              <ul className="mt-3 list-disc space-y-1 pl-5 text-sm leading-6 text-app-muted">
                <li>{t('account.fediverse.step1')}</li>
                <li>{t('account.fediverse.step2')}</li>
                <li>{t('account.fediverse.step3')}</li>
              </ul>
              <p className="mt-3 text-xs leading-5 text-app-muted">
                {t('account.fediverse.behaviorNote')}
              </p>
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
