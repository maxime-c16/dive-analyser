import { useContext } from 'react'
import SyncStatusContext, { SyncContextType } from '../contexts/SyncStatusContext'

/**
 * Hook to access sync status context
 * Must be used within SyncStatusProvider
 */
export const useSyncStatus = (): SyncContextType => {
  const context = useContext(SyncStatusContext)
  if (!context) {
    throw new Error('useSyncStatus must be used within SyncStatusProvider')
  }
  return context
}

export default useSyncStatus
