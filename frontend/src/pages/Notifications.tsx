import React, { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Bell, CalendarDays, CheckCheck, Check, Film, RefreshCw } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useNotifications } from '../components/Notifications'
import {
  listNotifications,
  type AppNotification,
  type CalendarNotificationView,
} from '../services/notificationsApi'
import { notificationText } from '../utils/notificationText'
import PageLoading from '../components/PageLoading'
import { MobileShellActions } from '../navigation/mobileShellActions'

function typeLabel(t: (key: string, options?: Record<string, unknown>) => string, type: string): string {
  return t(`notifications.types.${type}`, { defaultValue: type })
}

function formatWhen(iso: string | null, locale: string): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString(locale, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

/** "Dive of <date>" when the real session date is known and differs from the
 * day the row arrived (a synced clip can lag its session by days). The dive
 * date is naive in the app's timezone, so only its naive date part renders —
 * no timezone conversion for a calendar label. */
function sessionDateLabel(item: AppNotification, lang: string): string | null {
  if (item.type !== 'new_video' || !item.dive_date || !item.created_at) return null
  const diveDay = item.dive_date.slice(0, 10)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(diveDay)) return null
  const arrivalDay = item.created_at.slice(0, 10)
  if (diveDay === arrivalDay) return null
  const parsed = new Date(`${diveDay}T12:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return null
  const label = parsed.toLocaleDateString(lang, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
  return label
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
  const generated = notificationText(item, t)
  const title = calendar
    ? calendarView
      ? `${t(`notifications.calendar.${calendarView.kind}`)} · ${calendarView.event_title}`
      : typeLabel(t, item.type)
    : generated.title
  const body = calendar
    ? calendarView
      ? calendarLines(t, calendarView, lang).join(' · ')
      : t('notifications.calendar.redacted')
    : generated.body
  // The item carries the sync moment as its own date; when the server
  // resolved the dive's real session date and it differs, state it — the
  // "Open dive" action points at that session, not the arrival day.
  const diveDate = sessionDateLabel(item, lang)
  return (
    <article
      aria-label={title}
      className={`rounded-xl border border-app bg-app-panel p-4 ${unread ? 'border-l-2 border-l-[var(--app-accent)]' : ''}`}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-app-accent">
          {typeLabel(t, item.type)}
          {unread ? <span className="sr-only"> · {t('notifications.unreadBadge')}</span> : null}
        </p>
        {item.created_at && (
          <time dateTime={item.created_at} className="shrink-0 text-xs text-app-muted">
            {formatWhen(item.created_at, i18n.language)}
          </time>
        )}
      </div>
      <h2 className="mt-1 text-base font-semibold text-app-text">{title}</h2>
      {body && <p className="mt-1 text-sm leading-6 text-app-muted">{body}</p>}
      {diveDate && <p className="mt-1 text-xs text-app-muted">{t('notifications.diveDate', { date: diveDate })}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {calendarView && calendarView.url.startsWith('/calendar') && (
          <Link
            to={calendarView.url}
            className="touch-target inline-flex items-center gap-2 rounded-lg border border-app bg-app-panel-elevated px-3 py-2 text-sm font-medium text-app-text"
          >
            <CalendarDays className="h-4 w-4" aria-hidden />
            {t('notifications.calendar.openEvent')}
          </Link>
        )}
        {item.conversation_id != null && <Link to={`/messages/${item.conversation_id}`} className="touch-target inline-flex items-center rounded-lg border border-app px-3 py-2 text-sm text-app-text">{t('messages.open')}</Link>}
        {item.type === 'session_video' && (
          <Link
            to={item.session_id ? `/sessions/shared/${item.session_id}` : "/dives"}
            className="touch-target inline-flex items-center gap-2 rounded-lg border border-app bg-app-panel-elevated px-3 py-2 text-sm font-medium text-app-text"
          >
            <Film className="h-4 w-4" aria-hidden />
            {t('nav.dives')}
          </Link>
        )}
        {item.dive_id != null && (
          <Link
            to={`/dives?clip=${item.dive_id}`}
            className="touch-target inline-flex items-center gap-2 rounded-lg border border-app bg-app-panel-elevated px-3 py-2 text-sm font-medium text-app-text"
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
            className="touch-target inline-flex items-center gap-2 rounded-lg border border-app bg-transparent px-3 py-2 text-sm text-app-muted hover:text-app-text disabled:opacity-60"
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
  const { user } = useAuth()
  return <AccountNotificationsPage key={user?.user_id ?? 'anonymous'} />
}

function AccountNotificationsPage() {
  const { t } = useTranslation()
  const { items, unreadCount, loading, error, refreshTick, refresh, markRead, markAllRead, countsKnown, pageHasMore } = useNotifications()
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
  const [serverUnreadHasMore, setServerUnreadHasMore] = useState(false)

  // Explicit continuation beyond the first 50 rows, per current filter.
  // Kept separate from the provider page so a 60s poll never loses rows the
  // user already paged into view; switching filters rebuilds it.
  const [older, setOlder] = useState<AppNotification[]>([])
  const [olderCursor, setOlderCursor] = useState<number | null>(null)
  const [olderHasMore, setOlderHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const pageGeneration = useRef(0)
  const pendingPage = useRef(false)

  useEffect(() => {
    if (!unreadOnly) {
      setServerUnread(null)
      return
    }    let alive = true
    void (async () => {
      try {
        const data = await listNotifications({ unreadOnly: true, limit: 50 })
        if (!alive) return
        setServerUnread(data.items)
        setServerUnreadHasMore(data.has_more)
      } catch {
        if (alive) {
          setServerUnread(null)
          setServerUnreadHasMore(false)
        }
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

  // Continuation pages below are anchored to the last row already on
  // screen, so switching filters (and therefore re-anchoring) drops them.
  useEffect(() => {
    pendingPage.current = false
    setOlder([])
    setOlderCursor(null)
    setOlderHasMore(false)
    setLoadingMore(false)
    // A filter switch moves the head anchor (the unread stream's deepest
    // row differs from the all stream's). Record the fresh anchor as the
    // baseline instead of letting the rebase see "the head jumped" — a
    // switch announces no arrival, so server truth owns the control.
    headAnchorRef.current = null
    return () => { pageGeneration.current += 1 }
  }, [unreadOnly])

  // A refresh can displace rows out of the first page while the user has
  // paged past it: the head grows (61–12 replaces 60–11) and the rows between
  // the two heads (11) become unreachable from both lists — the dedup only
  // merges rows, it cannot reach a row beyond either cursor. When the head's
  // anchor moves forward while a continuation is loaded, rebase the cursor to
  // the fresh head anchor: the next "Show older" re-fetches the displaced
  // range from the server (bounded by the same limit; rows already loaded
  // merge instead of accumulating). A shrinking/removal head never rebases,
  // and rows are never dropped — only their cursor is moved forward.
  const headBase = unreadOnly ? (serverUnread ?? items) : items
  const headAnchor = headBase[headBase.length - 1]?.id ?? null
  const headAnchorRef = useRef<number | null>(null)
  useEffect(() => {
    const previous = headAnchorRef.current
    headAnchorRef.current = headAnchor
    if (previous === null || headAnchor === null || headAnchor <= previous) return
    // The head moved forward: align the continuation boundary to the fresh
    // head's deepest row, no matter what continuation is on the wire. The
    // generation bump ends the ownership of every request launched before
    // the rebase (success/error AND finally: none of them may clear the
    // pending fence of a newer page); the fence lifts here, the control is
    // actionable immediately, and the displaced rows arrive with the next
    // request (bounded by the same page limit).
    pageGeneration.current += 1
    if (olderCursor === null || headAnchor > olderCursor) {
      setOlderCursor(headAnchor)
    }
    setOlderHasMore(true)
    pendingPage.current = false
    setLoadingMore(false)
  }, [headAnchor, olderCursor])

  const firstPage = unreadOnly
    ? (serverUnread ?? items).filter(item => !item.read_at)
    : items
  // A refresh can move a continuation row into the first page. Prefer its
  // fresh server state and render each notification exactly once.
  const visible = [...new Map([...older, ...firstPage].map(item => [item.id, item])).values()]
    .filter(item => !unreadOnly || !item.read_at)
    .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? '') || b.id - a.id)

  // The "more" promise comes from whichever page is currently the deepest:
  // the provider/unread first fetch when nothing else has been loaded.
  const hasMore = loadingMore
    ? true
    : !unreadOnly
      ? olderCursor !== null ? olderHasMore : pageHasMore
      : serverUnread === null
        ? false
        : olderCursor !== null ? olderHasMore : serverUnreadHasMore

  const handleLoadMore = async () => {
    const base = unreadOnly ? (serverUnread ?? items) : items
    const anchor = olderCursor ?? base[base.length - 1]?.id ?? null
    if (anchor == null || pendingPage.current) return
    const generation = pageGeneration.current
    pendingPage.current = true
    setLoadingMore(true)
    setActionError(false)
    try {
      const data = await listNotifications({
        unreadOnly: unreadOnly || undefined,
        limit: 50,
        beforeId: anchor,
      })
      if (generation !== pageGeneration.current) return
      // Merge by id: a rebased cursor re-returns rows the user already
      // loaded, and the server's fresh copy must replace the stale one
      // without duplicating state.
      setOlder(previous => {
        const merged = new Map(previous.map(row => [row.id, row]))
        for (const row of data.items) merged.set(row.id, row)
        return [...merged.values()]
      })
      const next = data.items[data.items.length - 1]?.id ?? anchor
      setOlderCursor(next)
      setOlderHasMore(data.has_more)
    } catch {
      if (generation === pageGeneration.current) setActionError(true)
    } finally {
      if (generation === pageGeneration.current) {
        pendingPage.current = false
        setLoadingMore(false)
      }
    }
  }

  const handleMarkRead = async (id: number) => {
    setBusyId(id)
    setActionError(false)
    try {
      await markRead(id)
      if (unreadOnly) setServerUnread(prev => (prev ? prev.filter(item => item.id !== id) : prev))
      // The read state also applies to rows the user paged in beyond the
      // provider's first 50 (both filters keep their visible state).
      setOlder(prev => prev.map(item => (item.id === id ? { ...item, read_at: item.read_at ?? new Date().toISOString() } : item)))
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
      if (unreadOnly) {
        setServerUnread([])
        setServerUnreadHasMore(false)
      }
      pageGeneration.current += 1
      pendingPage.current = false
      setLoadingMore(false)
      setOlderHasMore(false)
      setOlder(prev => prev.map(item => ({ ...item, read_at: item.read_at ?? new Date().toISOString() })))
    } catch {
      setActionError(true)
    } finally {
      setBusyAll(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <header className="mb-5 border-b border-app pb-4">
        <div className="flex items-center gap-2">
          <h1 className="flex min-w-0 flex-1 items-center gap-2 text-3xl font-semibold tracking-tight text-app-text">
            <Bell className="h-6 w-6 text-app-accent max-lg:hidden" aria-hidden />
            {t('notifications.heading')}
          </h1>
          <MobileShellActions />
        </div>
      </header>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div role="group" aria-label={t('notifications.filterAria')} className="flex gap-1 rounded-full border border-app bg-app-panel p-1">
          <button
            type="button"
            aria-pressed={!unreadOnly}
            onClick={() => setUnreadOnly(false)}
            className={`min-h-9 rounded-full px-3 text-sm font-medium ${
              !unreadOnly
                ? 'bg-app-panel-elevated text-app-text shadow-[inset_0_0_0_1px_var(--app-border-strong)]'
                : 'text-app-muted hover:text-app-text'
            }`}
          >
            {t('notifications.showAll')}
          </button>
          <button
            type="button"
            aria-pressed={unreadOnly}
            onClick={() => setUnreadOnly(true)}
            className={`min-h-9 rounded-full px-3 text-sm font-medium ${
              unreadOnly
                ? 'bg-app-panel-elevated text-app-text shadow-[inset_0_0_0_1px_var(--app-border-strong)]'
                : 'text-app-muted hover:text-app-text'
            }`}
          >
            {countsKnown
              ? t('notifications.unreadOnly', { count: unreadCount })
              : t('notifications.unreadOnlyPending')}
          </button>
        </div>
        <button
          type="button"
          onClick={handleMarkAll}
          disabled={busyAll || unreadCount === 0}
          className="touch-target ml-auto inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded-full px-2 text-sm font-medium text-app-accent disabled:text-app-muted disabled:opacity-60"
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
        <PageLoading message={t('notifications.loading')} />
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
        <>
        <div className="grid gap-3" role="list" aria-label={t('notifications.listAria')}>
          {visible.map(item => (
            <div key={item.id} role="listitem">
              <NotificationRow item={item} onMarkRead={() => void handleMarkRead(item.id)} busy={busyId === item.id} />
            </div>
          ))}
        </div>
        {hasMore && (
          <button
            type="button"
            onClick={() => void handleLoadMore()}
            disabled={loadingMore}
            className="touch-target mt-4 inline-flex items-center gap-2 border border-app bg-app-panel-elevated px-4 py-2.5 text-sm font-medium text-app-text disabled:opacity-60"
          >
            {loadingMore ? t('common.loading') : t('notifications.loadMore')}
          </button>
        )}
        </>
      )}
    </div>
  )
}
