import React from 'react'
import { useSyncStatus } from '../hooks/useSyncStatus'
import SyncStatus from './SyncStatus'
import { AlertCircle, RefreshCw } from 'lucide-react'

interface JourneyWithSyncProps {
  children: React.ReactNode
  showSyncPanel?: boolean
  onSyncComplete?: () => void
}

/**
 * JourneyWithSync Component
 * Wraps journey content with real-time sync status panel
 */
export const JourneyWithSync: React.FC<JourneyWithSyncProps> = ({
  children,
  showSyncPanel = true,
  onSyncComplete,
}) => {
  const { currentSync, isConnected, connectionError } = useSyncStatus()

  // Notify when sync completes
  React.useEffect(() => {
    if (currentSync?.status === 'complete' && onSyncComplete) {
      onSyncComplete()
    }
  }, [currentSync?.status, onSyncComplete])

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Main Content */}
      <div className="lg:col-span-2">{children}</div>

      {/* Sync Panel */}
      {showSyncPanel && (
        <div className="space-y-4">
          {/* Sync Status Header */}
          <div className="rounded-lg p-4 border border-gray-800 bg-gray-900/50">
            <div className="flex items-center gap-2 mb-4">
              <div
                className={`w-3 h-3 rounded-full ${
                  isConnected ? 'bg-green-400' : 'bg-red-400'
                }`}
              />
              <h3 className="font-semibold">Live Sync</h3>
            </div>

            {/* Connection Status Badge */}
            {!isConnected && (
              <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 flex items-center gap-2">
                <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
                <div className="text-sm text-red-300">
                  {connectionError || 'Reconnecting...'}
                </div>
              </div>
            )}

            {/* Active Sync Indicator */}
            {currentSync && currentSync.status === 'in_progress' && (
              <div className="mb-4 p-3 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center gap-2">
                <RefreshCw className="w-4 h-4 text-cyan-400 animate-spin flex-shrink-0" />
                <div className="text-sm text-cyan-300">
                  Sync in progress: {currentSync.progress_percent}%
                </div>
              </div>
            )}
          </div>

          {/* Sync Details */}
          {showSyncPanel && <SyncStatus />}
        </div>
      )}
    </div>
  )
}

export default JourneyWithSync
