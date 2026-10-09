import { useBottomNotice } from '../navigation/useBottomNotice'
import { useTranslation } from 'react-i18next'
import React, { useState, useEffect, useRef } from 'react'
import { useSyncStatus } from '../hooks/useSyncStatus'
import { appLanguage } from '../utils/dateLocale'
import { AlertCircle, RotateCw, ChevronDown, ChevronUp, X } from 'lucide-react'

interface ErrorDetail {
  id: string
  timestamp: string
  message: string | null // null: no backend message, translated at render
  syncId: string
  retryCount: number
  expanded: boolean
}

/**
 * SyncErrorHandler Component
 * Displays sync errors with retry capabilities
 */
export const SyncErrorHandler: React.FC<{ maxErrors?: number }> = ({
  maxErrors = 5,
}) => {
  const { t } = useTranslation()
  const { currentSync, lastEvent } = useSyncStatus()
  const [errors, setErrors] = useState<ErrorDetail[]>([])
  const noticeElement = useRef<HTMLDivElement>(null)
  const showNotice = useBottomNotice(noticeElement, errors.length > 0)

  // Track new errors
  useEffect(() => {
    if (
      lastEvent?.type === 'sync_error' &&
      currentSync?.status === 'error'
    ) {
      const newError: ErrorDetail = {
        id: `error-${Date.now()}`,
        timestamp: lastEvent.timestamp,
        message: lastEvent.data.error || null,
        syncId: lastEvent.sync_id,
        retryCount: 0,
        expanded: true,
      }

      setErrors((prev) => {
        const updated = [newError, ...prev]
        return updated.slice(0, maxErrors)
      })

      // Auto-collapse after 5 seconds
      setTimeout(() => {
        setErrors((prev) =>
          prev.map((err) =>
            err.id === newError.id ? { ...err, expanded: false } : err
          )
        )
      }, 5000)
    }
  }, [lastEvent, currentSync, maxErrors])

  const toggleExpanded = (id: string) => {
    setErrors((prev) =>
      prev.map((err) =>
        err.id === id ? { ...err, expanded: !err.expanded } : err
      )
    )
  }

  const removeError = (id: string) => {
    setErrors((prev) => prev.filter((err) => err.id !== id))
  }

  const retrySync = (syncId: string) => {
    setErrors((prev) =>
      prev.map((err) =>
        err.syncId === syncId ? { ...err, retryCount: err.retryCount + 1 } : err
      )
    )
    // Retry logic would be implemented in parent component
    console.log(`Retrying sync: ${syncId}`)
  }

  if (errors.length === 0 || !showNotice) {
    return null
  }

  return (
    <div ref={noticeElement} className="mobile-bottom-notice fixed bottom-[calc(1.5rem+var(--mobile-nav-offset,0px))] left-6 z-40 space-y-2 max-w-md">
      {errors.map((error) => (
        <div
          key={error.id}
          className="rounded-lg border border-red-500/30 bg-red-500/10 overflow-hidden shadow-lg "
        >
          {/* Error Header */}
          <div className="p-4 flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />

            <div className="flex-1 min-w-0">
              <h4 className="font-semibold text-red-300 text-sm">{t("sync.error")}</h4>
              <p className="text-xs text-app-muted mt-1">
                {new Date(error.timestamp).toLocaleTimeString(appLanguage())}
              </p>
            </div>

            <button
              onClick={() => removeError(error.id)}
              className="text-app-muted hover:text-app-text flex-shrink-0"
              aria-label={t("sync.dismissError")}
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Expandable Error Details */}
          <button
            onClick={() => toggleExpanded(error.id)}
            className="w-full px-4 py-2 flex items-center gap-2 bg-red-500/5 border-t border-red-500/20 hover:bg-red-500/10 transition-colors text-left"
          >
            <span className="flex-1 text-sm text-app-text truncate">
              {error.message ?? t('sync.unknownError')}
            </span>
            {error.expanded ? (
              <ChevronUp className="w-4 h-4 text-red-400 flex-shrink-0" />
            ) : (
              <ChevronDown className="w-4 h-4 text-red-400 flex-shrink-0" />
            )}
          </button>

          {/* Expanded Details */}
          {error.expanded && (
            <div className="px-4 py-3 bg-app-bg space-y-3 border-t border-red-500/20">
              <div>
                <div className="text-xs text-app-muted mb-1">{t('sync.syncId')}</div>
                <code className="text-xs text-app-text bg-app-bg p-2 rounded block font-mono break-all">
                  {error.syncId}
                </code>
              </div>

              <div>
                <div className="text-xs text-app-muted mb-1">{t('sync.errorMessage')}</div>
                <p className="text-xs text-red-200 bg-app-bg p-2 rounded">
                  {error.message ?? t('sync.unknownError')}
                </p>
              </div>

              <div className="text-xs text-app-muted">
                {t('sync.retryAttempts')} <span className="font-bold">{error.retryCount}</span>
              </div>

              {/* Action Buttons */}
              <div className="flex gap-2 pt-2">
                <button
                  onClick={() => retrySync(error.syncId)}
                  className="flex-1 flex items-center justify-center gap-2 py-2 px-3 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded text-sm font-medium transition-colors"
                  disabled={error.retryCount >= 3}
                >
                  <RotateCw className="w-4 h-4" />
                  {t('sync.retry')}
                </button>

                <button
                  onClick={() => removeError(error.id)}
                  className="flex-1 py-2 px-3 bg-app-panel border border-app hover:text-app-text rounded text-sm font-medium transition-colors"
                >
                  {t('sync.dismiss')}
                </button>
              </div>

              {error.retryCount >= 3 && (
                <div className="p-2 bg-amber-500/10 border border-amber-500/30 rounded text-xs text-amber-300">
                  {t('sync.maxRetries')}
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

export default SyncErrorHandler
