import React, { useEffect, useState } from 'react'
import { api } from '../services/api'
import { format, parseISO, isToday, isYesterday, isThisWeek } from 'date-fns'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import SessionDetail from '../components/SessionDetail'
import RecentProgress from '../components/RecentProgress'
import SessionDirectionIndicator from '../components/SessionDirectionIndicator'

interface Session {
  id: number
  date: string
  location?: string
  total_dives: number
  total_personal_dives: number
  avg_performance?: number
  success_rate?: number
  notes?: string
}

function Sessions() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [limit, setLimit] = useState(50)
  const [selectedSession, setSelectedSession] = useState<Session | null>(null)

  useEffect(() => {
    fetchSessions()
  }, [limit])

  const fetchSessions = async () => {
    try {
      setLoading(true)
      const response = await api.get('/api/v1/sessions', {
        params: { limit },
      })
      setSessions(response.data)
      setError(null)
    } catch (err) {
      console.error('Error fetching sessions:', err)
      setError('Failed to load sessions')
    } finally {
      setLoading(false)
    }
  }

  // Group sessions by month
  const groupedSessions = sessions.reduce((groups, session) => {
    const monthKey = format(parseISO(session.date), 'MMMM yyyy')
    if (!groups[monthKey]) {
      groups[monthKey] = []
    }
    groups[monthKey].push(session)
    return groups
  }, {} as { [key: string]: Session[] })

  // Calculate stats
  const stats = {
    totalSessions: sessions.length,
    totalDives: sessions.reduce((sum, s) => sum + s.total_dives, 0),
    avgDivesPerSession: sessions.length > 0
      ? sessions.reduce((sum, s) => sum + s.total_dives, 0) / sessions.length
      : 0,
  }

  const getDateLabel = (dateStr: string) => {
    const date = parseISO(dateStr)
    if (isToday(date)) return 'Today'
    if (isYesterday(date)) return 'Yesterday'
    return format(date, 'EEEE, MMMM d')
  }

  const getPerformanceColor = (perf: number | undefined) => {
    if (!perf) return 'text-gray-500'
    if (perf >= 3) return 'text-green-400'
    if (perf >= 2) return 'text-amber-400'
    return 'text-red-400'
  }

  const getSuccessRateColor = (rate: number | undefined) => {
    if (!rate) return 'bg-gray-700 text-gray-400'
    if (rate >= 80) return 'bg-green-500/20 text-green-400'
    if (rate >= 60) return 'bg-amber-500/20 text-amber-400'
    return 'bg-red-500/20 text-red-400'
  }

  const getSessionBorderColor = (perf: number | undefined) => {
    if (!perf) return 'border-gray-700'
    if (perf >= 3) return 'border-green-500/50'
    if (perf >= 2.5) return 'border-amber-500/50'
    if (perf >= 2) return 'border-gray-600'
    return 'border-red-500/50'
  }

  const calculateTrend = (index: number) => {
    const currentSession = Object.values(groupedSessions).flat()[index]
    const previousSession = Object.values(groupedSessions).flat()[index + 1]

    if (!currentSession || !previousSession) return null

    const perfDiff = (currentSession.avg_performance || 0) - (previousSession.avg_performance || 0)

    return {
      isPositive: perfDiff > 0,
      isNeutral: perfDiff === 0,
    }
  }

  const TrendIndicator = ({ trend }: { trend: any }) => {
    if (!trend) return null
    if (trend.isNeutral) return <Minus className="w-4 h-4 text-gray-500" />
    return trend.isPositive
      ? <TrendingUp className="w-4 h-4 text-green-400" />
      : <TrendingDown className="w-4 h-4 text-red-400" />
  }

  const getPreviousSession = (sessionId: number): Session | undefined => {
    const allSessions = Object.values(groupedSessions).flat()
    const currentIndex = allSessions.findIndex(s => s.id === sessionId)
    return allSessions[currentIndex + 1]
  }

  return (
    <div className="p-6 space-y-6">
      {/* Session Detail Modal */}
      {selectedSession && (
        <SessionDetail
          session={selectedSession}
          previousSession={getPreviousSession(selectedSession.id)}
          allSessions={sessions}
          onClose={() => setSelectedSession(null)}
        />
      )}

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-white">Training Sessions</h1>
          <p className="text-gray-400 mt-1">Your training history by day</p>
        </div>

        {/* Quick Stats */}
        <div className="flex gap-4">
          <div className="bg-gray-800 px-4 py-2 rounded-lg border border-gray-700">
            <span className="text-gray-400 text-sm">Sessions</span>
            <span className="text-white font-bold ml-2">{stats.totalSessions}</span>
          </div>
          <div className="bg-gray-800 px-4 py-2 rounded-lg border border-gray-700">
            <span className="text-gray-400 text-sm">Total Dives</span>
            <span className="text-cyan-400 font-bold ml-2">{stats.totalDives}</span>
          </div>
          <div className="bg-gray-800 px-4 py-2 rounded-lg border border-gray-700">
            <span className="text-gray-400 text-sm">Avg/Session</span>
            <span className="text-purple-400 font-bold ml-2">{stats.avgDivesPerSession.toFixed(1)}</span>
          </div>
        </div>
      </div>

      {/* Recent Progress */}
      {!loading && !error && sessions.length > 0 && (
        <RecentProgress sessions={sessions} onSessionClick={setSelectedSession} />
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <div className="w-12 h-12 border-4 border-cyan-500 border-t-transparent rounded-full animate-spin"></div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-400">
          {error}
        </div>
      )}

      {/* Sessions by Month */}
      {!loading && !error && (
        <div className="space-y-8">
          {Object.entries(groupedSessions).map(([month, monthSessions]) => (
            <div key={month}>
              <h2 className="text-lg font-semibold text-gray-400 mb-4 flex items-center gap-2">
                <span className="w-2 h-2 bg-cyan-500 rounded-full"></span>
                {month}
                <span className="text-sm font-normal text-gray-500">
                  ({monthSessions.length} sessions)
                </span>
              </h2>

              <div className="grid gap-4">
                {monthSessions.map((session, sessionIndex) => {
                  const trend = calculateTrend(Object.values(groupedSessions).flat().indexOf(session))
                  return (
                    <button
                      key={session.id}
                      onClick={() => setSelectedSession(session)}
                      className={`bg-gray-800 rounded-xl p-5 border-2 ${getSessionBorderColor(session.avg_performance)} hover:border-cyan-500 transition text-left cursor-pointer`}
                    >
                      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                        {/* Date and Location */}
                        <div className="flex-1">
                          <div className="flex items-center gap-3">
                            <div className="w-12 h-12 bg-cyan-500/10 rounded-lg flex items-center justify-center">
                              <span className="text-2xl">🏊</span>
                            </div>
                            <div>
                              <h3 className="text-lg font-semibold text-white">
                                {getDateLabel(session.date)}
                              </h3>
                              <p className="text-gray-400 text-sm">
                                {session.location || format(parseISO(session.date), 'EEEE')}
                              </p>
                            </div>
                          </div>
                        </div>

                        {/* Stats */}
                        <div className="flex flex-wrap gap-6 lg:gap-8">
                          <div className="text-center">
                            <p className="text-2xl font-bold text-white">{session.total_dives}</p>
                            <p className="text-xs text-gray-500">Total Dives</p>
                          </div>
                          <div className="text-center">
                            <p className="text-2xl font-bold text-cyan-400">{session.total_personal_dives}</p>
                            <p className="text-xs text-gray-500">Personal</p>
                          </div>
                          <div className="text-center">
                            <div className="flex items-center justify-center gap-2">
                              <p className={`text-2xl font-bold ${getPerformanceColor(session.avg_performance)}`}>
                                {session.avg_performance?.toFixed(2) || '-'}
                              </p>
                              {trend && <TrendIndicator trend={trend} />}
                            </div>
                            <p className="text-xs text-gray-500">Avg Perf</p>
                          </div>
                          <div className="text-center">
                            <span className={`inline-block px-3 py-1 rounded-lg text-sm font-bold ${getSuccessRateColor(session.success_rate)}`}>
                              {session.success_rate ? `${session.success_rate.toFixed(0)}%` : '-'}
                            </span>
                            <p className="text-xs text-gray-500 mt-1">Success</p>
                          </div>
                        </div>
                      </div>

                      {/* Notes (if any) */}
                      {session.notes && (
                        <div className="mt-4 pt-4 border-t border-gray-700">
                          <p className="text-gray-400 text-sm">{session.notes}</p>
                        </div>
                      )}

                      {/* Performance bar */}
                      <div className="mt-4">
                        <div className="h-1 bg-gray-700 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all ${
                              (session.success_rate || 0) >= 80 ? 'bg-green-500' :
                              (session.success_rate || 0) >= 60 ? 'bg-amber-500' : 'bg-red-500'
                            }`}
                            style={{ width: `${session.success_rate || 0}%` }}
                          />
                        </div>
                      </div>

                      {/* Direction Indicators */}
                      <div className="mt-4 pt-4 border-t border-gray-700">
                        <SessionDirectionIndicator sessionId={session.id} />
                      </div>

                      {/* Click hint */}
                      <div className="mt-3 text-xs text-cyan-400">Click to view details →</div>
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && sessions.length === 0 && (
        <div className="text-center py-16">
          <div className="text-6xl mb-4">📅</div>
          <p className="text-gray-400 text-xl">No sessions found</p>
          <p className="text-gray-500 mt-2">Start training to see your sessions here</p>
        </div>
      )}

      {/* Load more */}
      {!loading && sessions.length >= limit && (
        <div className="text-center">
          <button
            onClick={() => setLimit(limit + 50)}
            className="bg-gray-800 hover:bg-gray-700 text-white px-6 py-2 rounded-lg border border-gray-700 transition"
          >
            Load more sessions
          </button>
        </div>
      )}
    </div>
  )
}

export default Sessions
