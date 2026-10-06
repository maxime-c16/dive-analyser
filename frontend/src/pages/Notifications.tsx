import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Bell, CheckCheck, Check, Film, RefreshCw } from 'lucide-react'
import { useNotifications } from '../components/Notifications'
import type { AppNotification } from '../services/notificationsApi'

function typeLabel(t: (key: string, options?: Record<string, unknown>) => string, type: string): string {
  return t(`notifications.types.${type}`, { defaultValue: type })
}

function formatWhen(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString()
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
  const { t } = useTranslation()
  const unread = !item.read_at
  return (
    <article
      aria-label={item.title}
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
      <h2 className="mt-1 text-base font-semibold text-app-text">{item.title}</h2>
      {item.body && <p className="mt-1 text-sm leading-6 text-app-muted">{item.body}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
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
  const { items, unreadCount, loading, error, refresh, markRead, markAllRead } = useNotifications()
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [busyAll, setBusyAll] = useState(false)
  const [actionError, setActionError] = useState(false)

  const visible = unreadOnly ? items.filter(item => !item.read_at) : items

  const handleMarkRead = async (id: number) => {
    setBusyId(id)
    setActionError(false)
    try {
      await markRead(id)
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
