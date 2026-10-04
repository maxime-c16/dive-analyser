import React from 'react'
import { useSyncStatus } from '../hooks/useSyncStatus'
import {
  AlertCircle,
  CheckCircle,
  Clock,
  Wifi,
  WifiOff,
  X,
  Download,
} from 'lucide-react'

/**
 * SyncStatus Component
 * Displays current sync operation status and connection state
 * Provides visual feedback on sync progress, errors, and milestones
 */
export const SyncStatus: React.FC<{ compact?: boolean }> = ({ compact = false }) => {
  const {
    isConnected,
    connectionError,
    currentSync,
    recentMilestones,
    removeMilestone,
  } = useSyncStatus()

  if (compact) {
    // Compact connection indicator
    return (
      <div className="flex items-center gap-2">
        {isConnected ? (
          <>
            <Wifi className="w-4 h-4 text-green-400 animate-pulse" />
            <span className="text-xs text-app-muted">Connected</span>
          </>
        ) : (
          <>
            <WifiOff className="w-4 h-4 text-red-400" />
            <span className="text-xs text-app-muted">Offline</span>
          </>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Connection Status */}
      <div
        className={`rounded-lg p-4 border ${
          isConnected
            ? 'bg-green-500/5 border-green-500/20'
            : 'bg-red-500/5 border-red-500/20'
        }`}
      >
        <div className="flex items-center gap-3">
          {isConnected ? (
            <>
              <Wifi className="w-5 h-5 text-green-400 animate-pulse" />
              <div>
                <div className="font-semibold text-green-400">Connected</div>
              </div>
            </>
          ) : (
            <>
              <WifiOff className="w-5 h-5 text-red-400" />
              <div>
                <div className="font-semibold text-red-400">Disconnected</div>
                <div className="text-sm text-app-muted">
                  {connectionError || 'Reconnecting…'}
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Current Sync Operation */}
      {currentSync && (
        <div className="rounded-lg p-4 border border-app-accent bg-app-accent-soft space-y-3">
          <div className="flex items-center gap-3">
            {currentSync.status === 'in_progress' ? (
              <Download className="w-5 h-5 text-app-accent animate-spin" />
            ) : currentSync.status === 'complete' ? (
              <CheckCircle className="w-5 h-5 text-green-400" />
            ) : currentSync.status === 'error' ? (
              <AlertCircle className="w-5 h-5 text-red-400" />
            ) : (
              <Clock className="w-5 h-5 text-amber-400" />
            )}
            <div className="flex-1">
              <div className="font-semibold capitalize">
                {currentSync.status === 'in_progress'
                  ? 'Sync in Progress'
                  : `Sync ${currentSync.status}`}
              </div>
              <div className="text-sm text-app-muted">
                ID: {currentSync.sync_id.substring(0, 8)}...
              </div>
            </div>
          </div>

          {/* Progress Bar */}
          {currentSync.status === 'in_progress' && (
            <div>
              <div className="flex justify-between items-center mb-2">
                <span className="text-sm text-app-text">
                  {currentSync.synced_count} / {currentSync.total_videos}
                </span>
                <span className="text-sm font-semibold text-app-accent">
                  {currentSync.progress_percent}%
                </span>
              </div>
              <div className="w-full bg-app-border rounded-full h-2 overflow-hidden">
                <div
                  className="bg-app-accent h-full transition-all duration-300"
                  style={{ width: `${currentSync.progress_percent}%` }}
                />
              </div>
            </div>
          )}

          {/* Error Message */}
          {currentSync.status === 'error' && currentSync.error_message && (
            <div className="text-sm text-red-300 bg-red-500/10 p-2 rounded border border-red-500/20">
              {currentSync.error_message}
            </div>
          )}

          {/* Stats */}
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div className="bg-app-panel-elevated rounded p-2">
              <div className="text-app-muted">Synced</div>
              <div className="font-bold text-app-accent">{currentSync.synced_count}</div>
            </div>
            <div className="bg-app-panel-elevated rounded p-2">
              <div className="text-app-muted">Errors</div>
              <div className="font-bold text-red-400">{currentSync.error_count}</div>
            </div>
            <div className="bg-app-panel-elevated rounded p-2">
              <div className="text-app-muted">Duration</div>
              <div className="font-bold text-amber-400">
                {currentSync.duration_seconds.toFixed(1)}s
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Recent Milestones */}
      {recentMilestones.length > 0 && (
        <div className="rounded-lg p-4 border border-green-500/20 bg-green-500/5 space-y-3">
          <div className="font-semibold text-green-400">
            Recent Milestones ({recentMilestones.length})
          </div>
          <div className="space-y-2 max-h-48 overflow-y-auto">
            {recentMilestones.map((milestone, idx) => (
              <div
                key={idx}
                className="flex items-start gap-2 p-2 bg-app-panel-elevated rounded border border-green-500/10"
              >
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-green-300 text-sm truncate">
                    {milestone.title}
                  </div>
                  <div className="text-xs text-app-muted line-clamp-2">
                    {milestone.narrative}
                  </div>
                </div>
                <button
                  onClick={() => removeMilestone(idx)}
                  className="text-app-muted hover:text-app-text flex-shrink-0"
                  aria-label="Dismiss milestone"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default SyncStatus
