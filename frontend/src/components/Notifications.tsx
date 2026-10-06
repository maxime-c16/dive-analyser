import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Bell } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import {
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type AppNotification,
} from '../services/notificationsApi'

export type NotificationsError = 'load' | 'update' | null

type NotificationsContextValue = {
  items: AppNotification[]
  unreadCount: number
  loading: boolean
  error: NotificationsError
  refresh: () => void
  markRead: (id: number) => Promise<void>
  markAllRead: () => Promise<void>
}

const NotificationsContext = createContext<NotificationsContextValue>({
  items: [],
  unreadCount: 0,
  loading: false,
  error: null,
  refresh: () => {},
  markRead: async () => {},
  markAllRead: async () => {},
})

export function useNotifications(): NotificationsContextValue {
  return useContext(NotificationsContext)
}

function videoPlaying(): boolean {
  try {
    return Array.from(document.querySelectorAll('video')).some(video => !video.paused)
  } catch {
    return false
  }
}

/**
 * Shared inbox state: one 60s poll feeds both the nav badge and the
 * /notifications page. Badge-only by design — no toast per notification,
 * so video playback is never interrupted; the scheduled poll simply skips
 * a tick while a clip is playing (same convention as WhatsNew).
 */
export function NotificationsProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  // Account changes remount the polling boundary, like WhatsNewProvider.
  return user ? (
    <AccountNotifications key={user.user_id}>{children}</AccountNotifications>
  ) : (
    <>{children}</>
  )
}

function AccountNotifications({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<AppNotification[]>([])
  const [unreadCount, setUnreadCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<NotificationsError>(null)
  const stateRef = useRef({ items, unreadCount })
  stateRef.current = { items, unreadCount }

  const load = useCallback(async () => {
    if (typeof document !== 'undefined') {
      if (document.visibilityState === 'hidden') return
      if (videoPlaying()) return
    }
    try {
      const data = await listNotifications({ limit: 50 })
      setItems(data.items)
      setUnreadCount(data.unread_count)
      setError(null)
    } catch {
      // The badge stays quiet on failure: last known count remains, the
      // /notifications page surfaces the error with a retry.
      if (stateRef.current.items.length === 0) setError('load')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    void load().finally(() => {
      if (cancelled) setLoading(false)
    })
    const refresh = () => {
      void load()
    }
    const timer = window.setInterval(refresh, 60_000)
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      cancelled = true
      window.clearInterval(timer)
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [load])

  const refresh = useCallback(() => {
    setLoading(true)
    void load()
  }, [load])

  const markRead = useCallback(async (id: number) => {
    const previous = stateRef.current
    setItems(items => items.map(item => (item.id === id ? { ...item, read_at: new Date().toISOString() } : item)))
    setUnreadCount(count => Math.max(0, count - (previous.items.find(item => item.id === id && !item.read_at) ? 1 : 0)))
    try {
      const updated = await markNotificationRead(id)
      setItems(items => items.map(item => (item.id === id ? updated : item)))
      const data = await listNotifications({ limit: 50 })
      setItems(data.items)
      setUnreadCount(data.unread_count)
      setError(null)
    } catch {
      setItems(previous.items)
      setUnreadCount(previous.unreadCount)
      setError('update')
      throw new Error('mark-read-failed')
    }
  }, [])

  const markAllRead = useCallback(async () => {
    const previous = stateRef.current
    const now = new Date().toISOString()
    setItems(items => items.map(item => (item.read_at ? item : { ...item, read_at: now })))
    setUnreadCount(0)
    try {
      await markAllNotificationsRead()
      setError(null)
    } catch {
      setItems(previous.items)
      setUnreadCount(previous.unreadCount)
      setError('update')
      throw new Error('mark-all-read-failed')
    }
  }, [])

  const value: NotificationsContextValue = {
    items,
    unreadCount,
    loading,
    error,
    refresh,
    markRead,
    markAllRead,
  }
  return <NotificationsContext.Provider value={value}>{children}</NotificationsContext.Provider>
}

/**
 * Bell + unread badge. Same visual language as WhatsNewButton (bordered
 * chip, accent icon) but a navigation link: it opens /notifications.
 */
export function NotificationsButton({ compact = false }: { compact?: boolean }) {
  const { unreadCount } = useNotifications()
  const { t } = useTranslation()
  const label =
    unreadCount > 0
      ? t('notifications.openAriaUnread', { count: unreadCount })
      : t('notifications.openAria')
  const display = unreadCount > 99 ? '99+' : String(unreadCount)
  return (
    <Link
      data-testid="notifications-button"
      to="/notifications"
      aria-label={label}
      className={`flex min-h-11 items-center gap-2 border border-app px-3 text-sm text-app-accent ${compact ? '' : 'w-full text-left'}`}
    >
      <Bell className="h-4 w-4 shrink-0" aria-hidden />
      <span className={compact ? 'hidden sm:inline' : ''}>{t('notifications.title')}</span>
      {unreadCount > 0 && (
        <span
          data-testid="notifications-badge"
          aria-hidden="true"
          className="ml-auto inline-flex min-h-5 min-w-5 items-center justify-center rounded-full bg-app-accent px-1.5 text-xs font-bold text-[#0d211c]"
        >
          {display}
        </span>
      )}
    </Link>
  )
}
