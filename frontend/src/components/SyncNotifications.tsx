import React, { useEffect, useState } from 'react'
import { useSyncStatus } from '../hooks/useSyncStatus'
import { AlertCircle, CheckCircle, Info, X } from 'lucide-react'

interface Toast {
  id: string
  type: 'success' | 'error' | 'info' | 'warning'
  title: string
  message: string
  duration?: number
}

/**
 * SyncNotifications Component
 * Displays toast-like notifications for sync events
 */
export const SyncNotifications: React.FC = () => {
  const { lastEvent, currentSync } = useSyncStatus()
  const [toasts, setToasts] = useState<Toast[]>([])

  // Handle new events
  useEffect(() => {
    if (!lastEvent) return

    let toast: Toast | null = null

    switch (lastEvent.type) {
      case 'sync_started':
        toast = {
          id: `${Date.now()}-started`,
          type: 'info',
          title: 'Sync Started',
          message: `Syncing ${lastEvent.data.total_videos} videos...`,
          duration: 3000,
        }
        break

      case 'sync_complete':
        toast = {
          id: `${Date.now()}-complete`,
          type: 'success',
          title: 'Sync Complete',
          message: `Successfully synced ${lastEvent.data.synced_count} videos`,
          duration: 5000,
        }
        break

      case 'sync_error':
        toast = {
          id: `${Date.now()}-error`,
          type: 'error',
          title: 'Sync Error',
          message: lastEvent.data.error || 'An error occurred during sync',
          duration: 7000,
        }
        break

      case 'milestone_detected':
        toast = {
          id: `${Date.now()}-milestone`,
          type: 'success',
          title: 'Milestone Unlocked',
          message: lastEvent.data.title,
          duration: 5000,
        }
        break
    }

    if (toast) {
      setToasts((prev) => [...prev, toast!])

      // Auto-remove after duration
      if (toast.duration) {
        setTimeout(() => {
          removeToast(toast!.id)
        }, toast.duration)
      }
    }
  }, [lastEvent])

  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }

  return (
    <div className="fixed bottom-6 right-6 z-50 space-y-3 pointer-events-none">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`rounded-lg p-4 shadow-lg border flex items-start gap-3 pointer-events-auto  ${
            toast.type === 'success'
              ? 'bg-green-500/10 border-green-500/30'
              : toast.type === 'error'
              ? 'bg-red-500/10 border-red-500/30'
              : toast.type === 'warning'
              ? 'bg-amber-500/10 border-amber-500/30'
              : 'bg-blue-500/10 border-blue-500/30'
          }`}
        >
          {toast.type === 'success' && (
            <CheckCircle
              className="w-5 h-5 text-green-400 flex-shrink-0 mt-0.5"
              aria-hidden
            />
          )}
          {toast.type === 'error' && (
            <AlertCircle
              className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5"
              aria-hidden
            />
          )}
          {toast.type === 'warning' && (
            <AlertCircle
              className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5"
              aria-hidden
            />
          )}
          {toast.type === 'info' && (
            <Info
              className="w-5 h-5 text-blue-400 flex-shrink-0 mt-0.5"
              aria-hidden
            />
          )}

          <div className="flex-1 min-w-0">
            <div
              className={`font-semibold text-sm ${
                toast.type === 'success'
                  ? 'text-green-300'
                  : toast.type === 'error'
                  ? 'text-red-300'
                  : toast.type === 'warning'
                  ? 'text-amber-300'
                  : 'text-blue-300'
              }`}
            >
              {toast.title}
            </div>
            <div className="text-sm text-app-text line-clamp-2">
              {toast.message}
            </div>
          </div>

          <button
            onClick={() => removeToast(toast.id)}
            className="text-app-muted hover:text-app-text flex-shrink-0"
            aria-label="Dismiss notification"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      ))}
    </div>
  )
}

export default SyncNotifications
