import React, { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../services/api'

interface SessionDirectionIndicatorProps {
  sessionId: number
  diverScope: 'self' | 'all'
}

const DIRECTION_COLORS: { [key: number]: string } = {
  1: '#3b82f6',
  2: '#10b981',
  3: '#f59e0b',
  4: '#f97316',
  5: '#ec4899',
}

function SessionDirectionIndicator({ sessionId, diverScope }: SessionDirectionIndicatorProps) {
  const { t } = useTranslation()
  const [directions, setDirections] = useState<number[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchDirections()
  }, [sessionId, diverScope])

  const fetchDirections = async () => {
    try {
      const response = await api.get('/api/v1/dives', {
        params: { session_id: sessionId, limit: 100, diver_scope: diverScope },
      })
      const dives = response.data || []
      const uniqueDirections = Array.from(new Set(dives.map((d: any) => d.direction).filter((d: any) => d !== null)))
        .sort() as number[]
      setDirections(uniqueDirections)
    } catch (err) {
      console.error('Error fetching directions:', err)
    } finally {
      setLoading(false)
    }
  }

  if (loading || directions.length === 0) {
    return null
  }

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs text-app-muted">{t('sessionDirection.label')}</span>
      <div className="flex gap-2">
        {directions.map((dir) => (
          <div
            key={dir}
            className="px-2.5 py-1 rounded-full flex items-center justify-center text-white text-xs font-bold transition-transform hover:scale-110"
            style={{ backgroundColor: DIRECTION_COLORS[dir] }}
            title={dir in DIRECTION_COLORS ? t(`groups.${dir}`) : undefined}
          >
            {dir in DIRECTION_COLORS ? t(`sessionDirection.short.${dir}`) : undefined}
          </div>
        ))}
      </div>
    </div>
  )
}

export default SessionDirectionIndicator
