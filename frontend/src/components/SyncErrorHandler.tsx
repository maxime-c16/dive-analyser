import React, { useState, useEffect } from 'react'
import { useSyncStatus } from '../hooks/useSyncStatus'
import { AlertCircle, RotateCw, ChevronDown, ChevronUp, X } from 'lucide-react'

interface ErrorDetail {
  id: string
  timestamp: string
  message: string
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
  const { currentSync, lastEvent } = useSyncStatus()
  const [errors, setErrors] = useState<ErrorDetail[]>([])

  // Track new errors
  useEffect(() => {
    if (
      lastEvent?.type === 'sync_error' &&
      currentSync?.status === 'error'
    ) {
      const newError: ErrorDetail = {
        id: `error-${Date.now()}`,
        timestamp: lastEvent.timestamp,
        message: lastEvent.data.error || 'Unknown error occurred',
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

  if (errors.length === 0) {
    return null
  }

  return (
    <div className="fixed bottom-6 left-6 z-40 space-y-2 max-w-md">
      {errors.map((error) => (
        <div
          key={error.id}
          className="rounded-lg border border-red-500/30 bg-red-500/10 overflow-hidden shadow-lg animate-in fade-in slide-in-from-left-2"
        >
          {/* Error Header */}
          <div className="p-4 flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />

            <div className="flex-1 min-w-0">
              <h4 className="font-semibold text-red-300 text-sm">Sync Error</h4>
              <p className="text-xs text-gray-400 mt-1">
                {new Date(error.timestamp).toLocaleTimeString()}
              </p>
            </div>

            <button
              onClick={() => removeError(error.id)}
              className="text-gray-400 hover:text-gray-300 flex-shrink-0"
              aria-label="Dismiss error"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Expandable Error Details */}
          <button
            onClick={() => toggleExpanded(error.id)}
            className="w-full px-4 py-2 flex items-center gap-2 bg-red-500/5 border-t border-red-500/20 hover:bg-red-500/10 transition-colors text-left"
          >
            <span className="flex-1 text-sm text-gray-300 truncate">
              {error.message}
            </span>
            {error.expanded ? (
              <ChevronUp className="w-4 h-4 text-red-400 flex-shrink-0" />
            ) : (
              <ChevronDown className="w-4 h-4 text-red-400 flex-shrink-0" />
            )}
          </button>

          {/* Expanded Details */}
          {error.expanded && (
            <div className="px-4 py-3 bg-black/20 space-y-3 border-t border-red-500/20">
              <div>
                <div className="text-xs text-gray-400 mb-1">Sync ID</div>
                <code className="text-xs text-gray-300 bg-black/50 p-2 rounded block font-mono break-all">
                  {error.syncId}
                </code>
              </div>

              <div>
                <div className="text-xs text-gray-400 mb-1">Error Message</div>
                <p className="text-xs text-red-200 bg-black/50 p-2 rounded">
                  {error.message}
                </p>
              </div>

              <div className="text-xs text-gray-400">
                Retry Attempts: <span className="font-bold">{error.retryCount}</span>
              </div>

              {/* Action Buttons */}
              <div className="flex gap-2 pt-2">
                <button
                  onClick={() => retrySync(error.syncId)}
                  className="flex-1 flex items-center justify-center gap-2 py-2 px-3 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded text-sm font-medium transition-colors"
                  disabled={error.retryCount >= 3}
                >
                  <RotateCw className="w-4 h-4" />
                  Retry
                </button>

                <button
                  onClick={() => removeError(error.id)}
                  className="flex-1 py-2 px-3 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded text-sm font-medium transition-colors"
                >
                  Dismiss
                </button>
              </div>

              {error.retryCount >= 3 && (
                <div className="p-2 bg-amber-500/10 border border-amber-500/30 rounded text-xs text-amber-300">
                  Maximum retry attempts reached. Please contact support if the issue persists.
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
