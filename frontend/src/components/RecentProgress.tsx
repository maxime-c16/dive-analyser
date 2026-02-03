import React from 'react'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { format, parseISO, isThisWeek, startOfWeek, endOfWeek } from 'date-fns'
import { LineChart, Line, ResponsiveContainer } from 'recharts'

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

interface RecentProgressProps {
  sessions: Session[]
  onSessionClick: (session: Session) => void
}

function RecentProgress({ sessions, onSessionClick }: RecentProgressProps) {
  // Get last 3 sessions
  const recentSessions = sessions.slice(0, 3)

  // Calculate trends
  const calculateTrend = (current: number | undefined, previous: number | undefined) => {
    if (!current || !previous) return null
    const diff = current - previous
    const percent = ((diff / previous) * 100).toFixed(1)
    return {
      percent,
      isPositive: diff > 0,
      isNeutral: diff === 0,
    }
  }

  // Filter sessions from this week only
  let thisWeekSessions = sessions.filter(session => isThisWeek(parseISO(session.date)))
  let weekLabel = 'This Week'
  let showWeekWarning = false
  let weekStart = startOfWeek(new Date())
  let weekEnd = endOfWeek(new Date())

  // If this week is empty, use the most recent week with data
  if (thisWeekSessions.length === 0 && sessions.length > 0) {
    const mostRecentSession = sessions[0]
    const mostRecentDate = parseISO(mostRecentSession.date)
    weekStart = startOfWeek(mostRecentDate)
    weekEnd = endOfWeek(mostRecentDate)

    thisWeekSessions = sessions.filter(session => {
      const sessionDate = parseISO(session.date)
      return sessionDate >= weekStart && sessionDate <= weekEnd
    })

    weekLabel = `${format(weekStart, 'MMM d')} - ${format(weekEnd, 'MMM d')}`
    showWeekWarning = true
  }

  // Calculate previous week stats for comparison
  const prevWeekStart = new Date(weekStart)
  prevWeekStart.setDate(prevWeekStart.getDate() - 7)
  const prevWeekEnd = new Date(weekEnd)
  prevWeekEnd.setDate(prevWeekEnd.getDate() - 7)

  const prevWeekSessions = sessions.filter(session => {
    const sessionDate = parseISO(session.date)
    return sessionDate >= prevWeekStart && sessionDate <= prevWeekEnd
  })

  // Calculate week stats
  const weekDives = thisWeekSessions.reduce((sum, s) => sum + s.total_dives, 0)
  const weekAvgPerf = thisWeekSessions.length > 0
    ? thisWeekSessions.reduce((sum, s) => sum + (s.avg_performance || 0), 0) / thisWeekSessions.length
    : 0

  // Calculate previous week stats
  const prevWeekDives = prevWeekSessions.reduce((sum, s) => sum + s.total_dives, 0)
  const prevWeekAvgPerf = prevWeekSessions.length > 0
    ? prevWeekSessions.reduce((sum, s) => sum + (s.avg_performance || 0), 0) / prevWeekSessions.length
    : 0

  // Calculate week trends
  const weekPerfTrend = prevWeekSessions.length > 0 ? calculateTrend(weekAvgPerf, prevWeekAvgPerf) : null
  const weekDivesTrend = prevWeekSessions.length > 0
    ? {
        value: Math.abs(weekDives - prevWeekDives),
        isPositive: weekDives > prevWeekDives,
        isNeutral: weekDives === prevWeekDives,
      }
    : null

  // Prepare data for mini chart
  const chartData = recentSessions.reverse().map((session) => ({
    date: format(parseISO(session.date), 'MMM d'),
    perf: session.avg_performance || 0,
    success: session.success_rate || 0,
  }))

  const perfTrend =
    recentSessions.length >= 2
      ? calculateTrend(recentSessions[0].avg_performance, recentSessions[1].avg_performance)
      : null

  const successTrend =
    recentSessions.length >= 2
      ? calculateTrend(recentSessions[0].success_rate, recentSessions[1].success_rate)
      : null

  const TrendIndicator = ({ trend }: { trend: any }) => {
    if (!trend) return <span className="text-gray-500 text-xs">-</span>
    if (trend.isNeutral) return <Minus className="w-3 h-3 text-gray-500" />
    const color = trend.isPositive ? 'text-green-400' : 'text-red-400'
    const Icon = trend.isPositive ? TrendingUp : TrendingDown
    return (
      <div className={`flex items-center gap-1 ${color}`}>
        <Icon className="w-3 h-3" />
        <span className="text-xs">{trend.percent}%</span>
      </div>
    )
  }

  if (recentSessions.length === 0) return null

  return (
    <div className="space-y-4">
      {/* Warning if showing past week */}
      {showWeekWarning && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-3 flex items-start gap-3">
          <span className="text-amber-400 text-lg">ℹ️</span>
          <div>
            <p className="text-amber-400 text-sm font-semibold">No sessions this week</p>
            <p className="text-amber-300/70 text-xs">Showing most recent week: {weekLabel}</p>
          </div>
        </div>
      )}

      {/* Week Overview */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {/* Total Dives Card */}
        <div className="bg-gradient-to-br from-cyan-500/20 to-cyan-600/10 border border-cyan-500/30 rounded-xl p-5 flex flex-col items-center justify-center text-center">
          <p className="text-cyan-400 text-xs font-semibold uppercase tracking-wider">{showWeekWarning ? 'Last Week' : 'This Week'}</p>
          <div className="mt-3 flex flex-col items-center">
            <p className="text-4xl font-bold text-white">{weekDives}</p>
            {weekDivesTrend && (
              <div className="mt-2 flex items-center justify-center gap-1.5">
                {weekDivesTrend.isPositive ? (
                  <TrendingUp className="w-4 h-4 text-green-400" />
                ) : weekDivesTrend.isNeutral ? (
                  <Minus className="w-4 h-4 text-gray-500" />
                ) : (
                  <TrendingDown className="w-4 h-4 text-red-400" />
                )}
                <span className="text-sm font-bold text-gray-300">{weekDivesTrend.value}</span>
              </div>
            )}
          </div>
          <p className="text-cyan-400 text-xs mt-3">Total Dives {weekDivesTrend ? 'vs prev' : ''}</p>
        </div>

        {/* Performance Card */}
        <div className="bg-gradient-to-br from-blue-500/20 to-blue-600/10 border border-blue-500/30 rounded-xl p-5 flex flex-col items-center justify-center text-center">
          <p className="text-blue-400 text-xs font-semibold uppercase tracking-wider">Performance</p>
          <div className="mt-3 flex flex-col items-center">
            <p className="text-4xl font-bold text-white">{weekAvgPerf.toFixed(2)}</p>
            {weekPerfTrend && (
              <div className="mt-2 flex items-center justify-center gap-1.5">
                {weekPerfTrend.isPositive ? (
                  <TrendingUp className="w-4 h-4 text-green-400" />
                ) : weekPerfTrend.isNeutral ? (
                  <Minus className="w-4 h-4 text-gray-500" />
                ) : (
                  <TrendingDown className="w-4 h-4 text-red-400" />
                )}
                <span className="text-sm font-bold text-gray-300">{weekPerfTrend.percent}%</span>
              </div>
            )}
          </div>
          <p className="text-blue-400 text-xs mt-3">Avg Perf {weekPerfTrend ? 'vs prev week' : ''}</p>
        </div>

        {/* Success Card */}
        <div className="bg-gradient-to-br from-green-500/20 to-green-600/10 border border-green-500/30 rounded-xl p-5 flex flex-col items-center justify-center text-center">
          <p className="text-green-400 text-xs font-semibold uppercase tracking-wider">Success</p>
          {recentSessions.length > 0 && (
            <div className="mt-3 flex flex-col items-center">
              <p className="text-4xl font-bold text-white">
                {(recentSessions[0].success_rate || 0).toFixed(0)}%
              </p>
              {successTrend && (
                <div className="mt-2 flex items-center justify-center gap-1.5">
                  {successTrend.isPositive ? (
                    <TrendingUp className="w-4 h-4 text-green-400" />
                  ) : successTrend.isNeutral ? (
                    <Minus className="w-4 h-4 text-gray-500" />
                  ) : (
                    <TrendingDown className="w-4 h-4 text-red-400" />
                  )}
                  <span className="text-sm font-bold text-gray-300">{successTrend.percent}%</span>
                </div>
              )}
            </div>
          )}
          <p className="text-green-400 text-xs mt-3">Latest {successTrend ? 'vs prev' : ''}</p>
        </div>

        {/* Sessions Card */}
        <div className="bg-gradient-to-br from-purple-500/20 to-purple-600/10 border border-purple-500/30 rounded-xl p-5 flex flex-col items-center justify-center text-center">
          <p className="text-purple-400 text-xs font-semibold uppercase tracking-wider">Sessions</p>
          <p className="text-4xl font-bold text-white mt-3">{recentSessions.length}</p>
          <p className="text-purple-400 text-xs mt-3">Recent</p>
        </div>
      </div>

      {/* Recent Sessions Cards */}
      <div className="space-y-3">
        <h3 className="text-lg font-semibold text-white flex items-center gap-2">
          <span className="w-2 h-2 bg-cyan-500 rounded-full"></span>
          Recent Sessions
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {recentSessions.map((session, index) => {
            const perfTrend =
              index < recentSessions.length - 1
                ? calculateTrend(session.avg_performance, recentSessions[index + 1].avg_performance)
                : null

            const successTrend =
              index < recentSessions.length - 1
                ? calculateTrend(session.success_rate, recentSessions[index + 1].success_rate)
                : null

            // Border color based on performance
            let borderColor = 'border-gray-700'
            if ((session.avg_performance || 0) >= 3) {
              borderColor = 'border-green-500/50'
            } else if ((session.avg_performance || 0) >= 2.5) {
              borderColor = 'border-amber-500/50'
            } else if ((session.avg_performance || 0) >= 2) {
              borderColor = 'border-gray-600'
            } else {
              borderColor = 'border-red-500/50'
            }

            return (
              <button
                key={session.id}
                onClick={() => onSessionClick(session)}
                className={`bg-gray-800 rounded-lg p-4 border ${borderColor} hover:border-cyan-500 transition text-left`}
              >
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <p className="text-white font-semibold text-sm">
                      {format(parseISO(session.date), 'MMM d')}
                    </p>
                    <p className="text-gray-500 text-xs mt-1">
                      {session.total_dives} dives
                    </p>
                  </div>
                  {index === 0 && (
                    <span className="bg-cyan-500/20 text-cyan-400 text-xs px-2 py-1 rounded">Latest</span>
                  )}
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-400">Performance</span>
                    <div className="flex items-center gap-2">
                      <span className="text-cyan-400 font-bold">{session.avg_performance?.toFixed(2)}</span>
                      {perfTrend ? (
                        <div className="flex items-center gap-0.5">
                          {perfTrend.isPositive ? (
                            <TrendingUp className="w-4 h-4 text-green-400" />
                          ) : perfTrend.isNeutral ? (
                            <Minus className="w-4 h-4 text-gray-500" />
                          ) : (
                            <TrendingDown className="w-4 h-4 text-red-400" />
                          )}
                          <span className="text-xs font-semibold text-gray-400">{Math.abs(parseFloat(perfTrend.percent))}%</span>
                        </div>
                      ) : (
                        <span className="text-xs text-gray-600">-</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-400">Success Rate</span>
                    <div className="flex items-center gap-2">
                      <span className="text-green-400 font-bold">{session.success_rate?.toFixed(0)}%</span>
                      {successTrend ? (
                        <div className="flex items-center gap-0.5">
                          {successTrend.isPositive ? (
                            <TrendingUp className="w-4 h-4 text-green-400" />
                          ) : successTrend.isNeutral ? (
                            <Minus className="w-4 h-4 text-gray-500" />
                          ) : (
                            <TrendingDown className="w-4 h-4 text-red-400" />
                          )}
                          <span className="text-xs font-semibold text-gray-400">{Math.abs(parseFloat(successTrend.percent))}%</span>
                        </div>
                      ) : (
                        <span className="text-xs text-gray-600">-</span>
                      )}
                    </div>
                  </div>
                </div>

                <div className="mt-3 pt-3 border-t border-gray-700">
                  <p className="text-xs text-cyan-400 hover:text-cyan-300 transition">View Details →</p>
                </div>
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export default RecentProgress
