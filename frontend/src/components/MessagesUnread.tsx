import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../contexts/AuthContext'
import { getUnreadCount } from '../services/messagesApi'
import { primaryTabFor } from '../navigation/mobileNavigation'

type MessagesUnreadContextValue = {
  /** Sum of unread_count across the inbox pages the badge polls. */
  unreadCount: number
  /** Re-read the inbox now (after a read receipt, on focus, on demand). */
  refresh: () => void
}

const MessagesUnreadContext = createContext<MessagesUnreadContextValue>({
  unreadCount: 0,
  refresh: () => {},
})

export function useMessagesUnread(): MessagesUnreadContextValue {
  return useContext(MessagesUnreadContext)
}

export function MessagesUnreadProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  // Account changes remount the polling boundary, like NotificationsProvider.
  return user ? (
    <AccountMessagesUnread key={user.user_id}>{children}</AccountMessagesUnread>
  ) : (
    <>{children}</>
  )
}

function AccountMessagesUnread({ children }: { children: React.ReactNode }) {
  const [unreadCount, setUnreadCount] = useState(0)
  const request = useRef(0)

  const refresh = useCallback(async () => {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
    const ticket = ++request.current
    try {
      // One bounded server-side aggregate: the inbox pages cap at 50 rows, so
      // summing client-side would hide unread conversations further down.
      const data = await getUnreadCount()
      // A poll or a receipt-triggered refresh started later wins; a late
      // response must never restore a count the user has already cleared.
      if (ticket !== request.current) return
      setUnreadCount(data.unread_count)
    } catch {
      // Badge-only: keep the last known count, never surface an error here.
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 20_000)
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [refresh])

  // Stable identity: consumers call it from effects and read receipts.
  const refreshNow = useCallback(() => { void refresh() }, [refresh])
  const value = useMemo(() => ({ unreadCount, refresh: refreshNow }), [unreadCount, refreshNow])
  return <MessagesUnreadContext.Provider value={value}>{children}</MessagesUnreadContext.Provider>
}

/**
 * Unread messages the user is NOT currently looking at: opening the Messages
 * tab discards the badge immediately, and the thread's read receipts plus
 * refresh() keep the count honest once the conversation has actually been read.
 */
function useVisibleUnreadCount(): number {
  const { unreadCount } = useMessagesUnread()
  const location = useLocation()
  return primaryTabFor(location.pathname) === 'messages' ? 0 : unreadCount
}

/** Accessible nav label mentioning the unread count, or undefined when clear. */
export function useMessagesUnreadAria(): string | undefined {
  const count = useVisibleUnreadCount()
  const { t } = useTranslation()
  return count > 0 ? t('nav.messagesUnreadAria', { count }) : undefined
}

/** Accent pill with the unread total; app style matches the bell badge. */
export function MessagesUnreadBadge({ className = '' }: { className?: string }) {
  const count = useVisibleUnreadCount()
  if (count <= 0) return null
  return (
    <span
      data-testid="messages-unread-badge"
      aria-hidden="true"
      className={`inline-flex min-h-5 min-w-5 items-center justify-center rounded-full bg-app-accent px-1.5 text-xs font-bold leading-none text-[#0d211c] ${className}`}
    >
      {count > 99 ? '99+' : count}
    </span>
  )
}
