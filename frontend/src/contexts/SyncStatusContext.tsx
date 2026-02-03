import React, { createContext, useState, useCallback, useEffect } from 'react'

export type SyncEventType =
  | 'sync_started'
  | 'sync_progress'
  | 'sync_complete'
  | 'sync_error'
  | 'milestone_detected'
  | 'heartbeat'

export interface SyncEvent {
  type: SyncEventType
  timestamp: string
  sync_id: string
  data: Record<string, any>
}

export interface SyncStatus {
  sync_id: string
  status: 'started' | 'in_progress' | 'complete' | 'error'
  total_videos: number
  synced_count: number
  error_count: number
  progress_percent: number
  duration_seconds: number
  error_message?: string
}

export interface SyncMilestone {
  type: string
  title: string
  narrative: string
  date: string
}

export interface SyncContextType {
  // Connection state
  isConnected: boolean
  connectionError: string | null
  clientId: string

  // Current sync state
  currentSync: SyncStatus | null
  recentMilestones: SyncMilestone[]
  lastEvent: SyncEvent | null

  // History
  syncHistory: SyncStatus[]
  maxHistorySize: number

  // Control methods
  connect: () => void
  disconnect: () => void
  getStatus: (syncId: string) => void
  clearHistory: () => void
  removeMilestone: (index: number) => void
}

const SyncStatusContext = createContext<SyncContextType | undefined>(undefined)

export const SyncStatusProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  // Connection state
  const [isConnected, setIsConnected] = useState(false)
  const [connectionError, setConnectionError] = useState<string | null>(null)
  const [clientId] = useState(() => {
    // Generate or retrieve persistent client ID
    let id = sessionStorage.getItem('sync_client_id')
    if (!id) {
      id = `client_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
      sessionStorage.setItem('sync_client_id', id)
    }
    return id
  })

  // WebSocket connection
  const [ws, setWs] = useState<WebSocket | null>(null)

  // Sync state
  const [currentSync, setCurrentSync] = useState<SyncStatus | null>(null)
  const [recentMilestones, setRecentMilestones] = useState<SyncMilestone[]>([])
  const [lastEvent, setLastEvent] = useState<SyncEvent | null>(null)
  const [syncHistory, setSyncHistory] = useState<SyncStatus[]>([])
  const maxHistorySize = 50

  // WebSocket URL construction
  const getWebSocketUrl = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    // Always use the current host (window.location.host) which is the proxy entry point
    // This works for both local dev and production through Nginx
    return `${protocol}//${window.location.host}/api/v1/ws/sync?client_id=${clientId}`
  }, [clientId])

  // Connect to WebSocket
  const connect = useCallback(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      console.log('Already connected to WebSocket')
      return
    }

    try {
      const url = getWebSocketUrl()
      console.log('Connecting to WebSocket:', url)
      const newWs = new WebSocket(url)

      newWs.onopen = () => {
        console.log('WebSocket connected')
        setIsConnected(true)
        setConnectionError(null)
      }

      newWs.onmessage = (event) => {
        try {
          const message: SyncEvent = JSON.parse(event.data)
          setLastEvent(message)

          // Handle different event types
          switch (message.type) {
            case 'sync_started':
              setCurrentSync({
                sync_id: message.sync_id,
                status: 'started',
                total_videos: message.data.total_videos,
                synced_count: 0,
                error_count: 0,
                progress_percent: 0,
                duration_seconds: 0,
              })
              break

            case 'sync_progress':
              setCurrentSync((prev) =>
                prev && prev.sync_id === message.sync_id
                  ? {
                      ...prev,
                      status: 'in_progress',
                      synced_count: message.data.synced_count,
                      error_count: message.data.error_count,
                      progress_percent: message.data.progress_percent,
                    }
                  : prev
              )
              break

            case 'sync_complete':
              setCurrentSync((prev) =>
                prev && prev.sync_id === message.sync_id
                  ? {
                      ...prev,
                      status: 'complete',
                      synced_count: message.data.synced_count,
                    }
                  : prev
              )
              // Add to history
              if (currentSync && currentSync.sync_id === message.sync_id) {
                setSyncHistory((prev) => {
                  const updated = [...prev, { ...currentSync, status: 'complete' }]
                  return updated.slice(-maxHistorySize)
                })
              }
              // Clear current sync after a delay
              setTimeout(() => setCurrentSync(null), 5000)
              break

            case 'sync_error':
              setCurrentSync((prev) =>
                prev && prev.sync_id === message.sync_id
                  ? {
                      ...prev,
                      status: 'error',
                      error_message: message.data.error,
                    }
                  : prev
              )
              break

            case 'milestone_detected':
              const milestone: SyncMilestone = {
                type: message.data.type,
                title: message.data.title,
                narrative: message.data.narrative,
                date: message.timestamp,
              }
              setRecentMilestones((prev) => [milestone, ...prev].slice(0, 10))
              break

            case 'heartbeat':
              // Connection heartbeat - just acknowledge
              console.debug('Heartbeat received')
              break
          }
        } catch (err) {
          console.error('Failed to parse WebSocket message:', err)
        }
      }

      newWs.onerror = (event) => {
        console.error('WebSocket error:', event)
        const error = 'WebSocket connection error'
        setConnectionError(error)
        setIsConnected(false)
      }

      newWs.onclose = () => {
        console.log('WebSocket disconnected')
        setIsConnected(false)
        setWs(null)
        // Attempt reconnection after 5 seconds
        setTimeout(connect, 5000)
      }

      setWs(newWs)
    } catch (err) {
      const error = err instanceof Error ? err.message : 'Connection failed'
      setConnectionError(error)
      setIsConnected(false)
    }
  }, [ws, getWebSocketUrl, currentSync])

  // Disconnect from WebSocket
  const disconnect = useCallback(() => {
    if (ws) {
      ws.close()
      setWs(null)
      setIsConnected(false)
    }
  }, [ws])

  // Request sync status
  const getStatus = useCallback(
    (syncId: string) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(
          JSON.stringify({
            type: 'get_status',
            sync_id: syncId,
          })
        )
      }
    },
    [ws]
  )

  // Auto-connect on mount
  useEffect(() => {
    connect()
    return () => {
      disconnect()
    }
  }, [])

  // Heartbeat to keep connection alive
  useEffect(() => {
    if (!isConnected || !ws) return

    const heartbeatInterval = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(
          JSON.stringify({
            type: 'heartbeat',
          })
        )
      }
    }, 30000) // Every 30 seconds

    return () => clearInterval(heartbeatInterval)
  }, [isConnected, ws])

  const value: SyncContextType = {
    isConnected,
    connectionError,
    clientId,
    currentSync,
    recentMilestones,
    lastEvent,
    syncHistory,
    maxHistorySize,
    connect,
    disconnect,
    getStatus,
    clearHistory: () => setSyncHistory([]),
    removeMilestone: (index: number) => {
      setRecentMilestones((prev) => prev.filter((_, i) => i !== index))
    },
  }

  return (
    <SyncStatusContext.Provider value={value}>
      {children}
    </SyncStatusContext.Provider>
  )
}

export default SyncStatusContext
