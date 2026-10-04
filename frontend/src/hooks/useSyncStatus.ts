import { useContext } from 'react'
import SyncStatusContext, { SyncContextType } from '../contexts/SyncStatusContext'

const fallbackSyncStatus: SyncContextType = {
  isConnected: false,
  connectionError: null,
  clientId: 'disabled',
  currentSync: null,
  recentMilestones: [],
  lastEvent: null,
  syncHistory: [],
  maxHistorySize: 50,
  connect: () => undefined,
  disconnect: () => undefined,
  getStatus: () => undefined,
  clearHistory: () => undefined,
  removeMilestone: () => undefined,
}

/**
 * Hook to access sync status context. The app root provides the context in
 * normal runtime, but a safe fallback prevents lazy chunk/provider drift from
 * crashing the whole UI.
 */
export const useSyncStatus = (): SyncContextType => {
  const context = useContext(SyncStatusContext)
  return context ?? fallbackSyncStatus
}

export default useSyncStatus
