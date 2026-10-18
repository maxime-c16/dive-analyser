import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Bell, CalendarDays, CheckCheck, Check, Film, RefreshCw } from 'lucide-react'
import { useNotifications } from '../components/Notifications'
import {
  listNotifications,
  type AppNotification,
  type CalendarNotificationView,
} from '../services/notificationsApi'

function typeLabel(t: (key: string, options?: Record<string, unknown>) => string, type: string): string {
  return t(`notifications.types.${type}`, { defaultValue: type })
}

function formatWhen(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString()
}

type Translate = (key: string, options?: Record<string, unknown>) => string

/** Event time in the event's own timezone (all-day: the local date). */
function eventWhen(iso: string | null, timeZone: string, lang: string, allDay = false): string {
  if (!iso) return ''
  const date = new Date(allDay && iso.length === 10 ? `${iso}T12:00:00Z` : iso)
  if (Number.isNaN(date.getTime())) return ''
  try {
    return date.toLocaleString(lang, allDay
      ? { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' }
      : { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone })
  } catch {
    return date.toLocaleString(lang)
  }
}

/** Plain-language lines for a calendar alert: what changed, when. */
function calendarLines(t: Translate, view: Extract<CalendarNotificationView, { redacted: false }>, lang: string): string[] {
  const lines: string[] = []
  const when = view.all_day
    ? eventWhen(view.start_date, view.timezone, lang, true)
    : eventWhen(view.starts_at, view.timezone, lang)
  if (view.status === 'cancelled') lines.push(t('notifications.calendar.eventCancelled'))
  for (const change of view.changes) {
    if (change.kinds.includes('time_changed') && change.old_start && change.new_start) {
      lines.push(t('notifications.calendar.moved', {
        from: eventWhen(change.old_start, view.timezone, lang),
        to: eventWhen(change.new_start, view.timezone, lang),
      }))
    }
    if (change.kinds.includes('venue_changed')) {
      lines.push(view.venue_name
        ? t('notifications.calendar.venueChanged', { venue: view.venue_name })
        : t('notifications.calendar.venueChangedNoName'))
    }
  }
  if (view.total > view.changes.length) {
    lines.push(t('notifications.calendar.more', { count: view.total - view.changes.length }))
  }
  if (lines.length === 0 && when) lines.push(when)
  return Array.from(new Set(lines))
}

function NotificationRow({
  item,
  onMarkRead,
  busy,
}: {
  item: AppNotification
  onMarkRead: () => void
  busy: boolean
}) {
  const { t, i18n } = useTranslation()
  const unread = !item.read_at
  const lang = i18n.resolvedLanguage?.startsWith('fr') ? 'fr' : 'en'
  const calendar = item.calendar
  const calendarView = calendar && !calendar.redacted ? calendar : null
  const title = calendar
    ? calendarView
      ? `${t(`notifications.calendar.${calendarView.kind}`)} · ${calendarView.event_title}`
      : typeLabel(t, item.type)
    : item.title
  const body = calendar
    ? calendarView
      ? calendarLines(t, calendarView, lang).join(' · ')
      : t('notifications.calendar.redacted')
    : item.body
  return (
    <article
      aria-label={title}
      className={`border border-app bg-app-panel p-4 ${unread ? 'border-l-2 border-l-[var(--app-accent)]' : ''}`}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-app-accent">
          {typeLabel(t, item.type)}
          {unread ? ` · ${t('notifications.unreadBadge')}` : ''}
        </p>
        {item.created_at && (
          <time dateTime={item.created_at} className="shrink-0 text-xs text-app-muted">
            {formatWhen(item.created_at)}
          </time>
        )}
      </div>
      <h2 className="mt-1 text-base font-semibold text-app-text">{title}</h2>
      {body && <p className="mt-1 text-sm leading-6 text-app-muted">{body}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {calendarView && calendarView.url.startsWith('/calendar') && (
          <Link
            to={calendarView.url}
            className="touch-target inline-flex items-center gap-2 border border-app bg-app-panel-elevated px-3 py-2 text-sm font-medium text-app-text"
          >
            <CalendarDays className="h-4 w-4" aria-hidden />
            {t('notifications.calendar.openEvent')}
          </Link>
        )}
        {item.conversation_id != null && <Link to={`/messages/${item.conversation_id}`} className="touch-target border border-app px-3 py-2 text-sm text-app-text">{t('messages.open')}</Link>}
        {item.dive_id != null && (
          <Link
            to={`/dives?clip=${item.dive_id}`}
            className="touch-target inline-flex items-center gap-2 border border-app bg-app-panel-elevated px-3 py-2 text-sm font-medium text-app-text"
          >
            <Film className="h-4 w-4" aria-hidden />
            {t('notifications.openDive')}
          </Link>
        )}
        {unread && (
          <button
            type="button"
            onClick={onMarkRead}
            disabled={busy}
            className="touch-target inline-flex items-center gap-2 border border-app bg-transparent px-3 py-2 text-sm text-app-muted hover:text-app-text disabled:opacity-60"
          >
            <Check className="h-4 w-4" aria-hidden />
            {t('notifications.markRead')}
          </button>
        )}
      </div>
    </article>
  )
}

export default function Notifications() {
  const { t } = useTranslation()
  const { items, unreadCount, loading, error, refreshTick, refresh, markRead, markAllRead } = useNotifications()
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [busyAll, setBusyAll] = useState(false)
  const [actionError, setActionError] = useState(false)
  // Server-fetched unread page (limit 50, like the provider). The badge
  // counts every unread row, but the provider only holds the 50 newest, so
  // filtering it in memory would hide older unread rows. When the unread
  // filter is on, refetch with unread_only=true instead; until the response
  // arrives (or when it fails) fall back to the in-memory filter.
  const [serverUnread, setServerUnread] = useState<AppNotification[] | null>(null)

  useEffect(() => {
    if (!unreadOnly) {
      setServerUnread(null)
      return
    }
    let alive = true
    void (async () => {
      try {
        const data = await listNotifications({ unreadOnly: true, limit: 50 })
        if (alive) setServerUnread(data.items)
      } catch {
        if (alive) setServerUnread(null)
      }
    })()
    return () => {
      alive = false
    }
    // refreshTick replays the unread_only fetch whenever the provider poll
    // (60s, focus, visibility) succeeds, so arrivals visible in the badge
    // also appear in the filtered list. Same query as the filter, so no
    // dedup needed: the provider holds the 50 newest, this holds the 50
    // newest unread.
  }, [unreadOnly, refreshTick])

  const visible = unreadOnly
    ? (serverUnread ?? items).filter(item => !item.read_at)
    : items

  const handleMarkRead = async (id: number) => {
    setBusyId(id)
    setActionError(false)
    try {
      await markRead(id)
      if (unreadOnly) setServerUnread(prev => (prev ? prev.filter(item => item.id !== id) : prev))
    } catch {
      setActionError(true)
    } finally {
      setBusyId(null)
    }
  }

  const handleMarkAll = async () => {
    setBusyAll(true)
    setActionError(false)
    try {
      await markAllRead()
      if (unreadOnly) setServerUnread([])
    } catch {
      setActionError(true)
    } finally {
      setBusyAll(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <header className="mb-5 border-b border-app pb-4">
        <h1 className="flex items-center gap-2 text-3xl font-semibold tracking-tight text-app-text">
          <Bell className="h-6 w-6 text-app-accent" aria-hidden />
          {t('notifications.heading')}
        </h1>
        <p className="mt-1 text-sm text-app-muted">{t('notifications.headingDesc')}</p>
      </header>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div role="group" aria-label={t('notifications.filterAria')} className="flex gap-2">
          <button
            type="button"
            aria-pressed={!unreadOnly}
            onClick={() => setUnreadOnly(false)}
            className={`touch-target border px-3 py-2 text-sm font-medium ${
              !unreadOnly
                ? 'border-app-accent bg-app-accent/10 text-app-accent'
                : 'border-app bg-app-panel-elevated text-app-muted hover:text-app-text'
            }`}
          >
            {t('notifications.showAll')}
          </button>
          <button
            type="button"
            aria-pressed={unreadOnly}
            onClick={() => setUnreadOnly(true)}
            className={`touch-target border px-3 py-2 text-sm font-medium ${
              unreadOnly
                ? 'border-app-accent bg-app-accent/10 text-app-accent'
                : 'border-app bg-app-panel-elevated text-app-muted hover:text-app-text'
            }`}
          >
            {t('notifications.unreadOnly', { count: unreadCount })}
          </button>
        </div>
        <button
          type="button"
          onClick={handleMarkAll}
          disabled={busyAll || unreadCount === 0}
          className="touch-target ml-auto inline-flex items-center gap-2 border border-app bg-app-panel-elevated px-3 py-2 text-sm font-medium text-app-text disabled:opacity-60"
        >
          <CheckCheck className="h-4 w-4" aria-hidden />
          {busyAll ? t('notifications.saving') : t('notifications.markAllRead')}
        </button>
      </div>

      {(actionError || error === 'update') && (
        <p role="alert" className="mb-4 border border-app bg-app-panel p-3 text-sm text-red-400">
          {t('notifications.errorAction')}
        </p>
      )}

      {loading && items.length === 0 ? (
        <p role="status" className="py-8 text-center text-sm text-app-muted">
          {t('notifications.loading')}
        </p>
      ) : error === 'load' && items.length === 0 ? (
        <div className="border border-app bg-app-panel p-8 text-center" role="alert">
          <p className="text-sm text-app-muted">{t('notifications.errorLoad')}</p>
          <button
            type="button"
            onClick={refresh}
            className="touch-target mt-4 inline-flex items-center gap-2 border border-app bg-app-panel-elevated px-4 py-2.5 text-sm font-medium text-app-text"
          >
            <RefreshCw className="h-4 w-4" aria-hidden />
            {t('common.retry')}
          </button>
        </div>
      ) : visible.length === 0 ? (
        <div className="border border-app bg-app-panel p-8 text-center" role="status">
          <Bell className="mx-auto h-8 w-8 text-app-muted" aria-hidden />
          <p className="mt-3 font-medium text-app-text">
            {unreadOnly ? t('notifications.emptyUnread') : t('notifications.emptyAll')}
          </p>
          <p className="mt-1 text-sm text-app-muted">{t('notifications.emptyHint')}</p>
        </div>
      ) : (
        <div className="grid gap-3" role="list" aria-label={t('notifications.listAria')}>
          {visible.map(item => (
            <div key={item.id} role="listitem">
              <NotificationRow item={item} onMarkRead={() => void handleMarkRead(item.id)} busy={busyId === item.id} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
