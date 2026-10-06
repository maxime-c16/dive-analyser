import React from 'react'
import { TrendingUp, TrendingDown, Minus, Info } from 'lucide-react'
import { format, parseISO, startOfDay, endOfDay, startOfWeek, endOfWeek, subDays } from 'date-fns'
import { appLocale } from '../utils/dateLocale'
import { LineChart, Line, ResponsiveContainer } from 'recharts'
import { performanceBorder, performanceColor } from '../utils/performanceScoring'

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

  // Use a rolling period, not a calendar week. A session on Saturday should
  // still be recent on Sunday rather than immediately becoming "last week".
  const now = new Date()
  const rollingStart = startOfDay(subDays(now, 6))
  const rollingEnd = endOfDay(now)
  let thisWeekSessions = sessions.filter((session) => {
    const date = parseISO(session.date)
    return date >= rollingStart && date <= rollingEnd
  })
  let weekLabel = `${format(rollingStart, 'MMM d', { locale: appLocale() })} - ${format(rollingEnd, 'MMM d', { locale: appLocale() })}`
  let showWeekWarning = false
  let weekStart = rollingStart
  let weekEnd = rollingEnd

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

    weekLabel = `${format(weekStart, 'MMM d', { locale: appLocale() })} - ${format(weekEnd, 'MMM d', { locale: appLocale() })}`
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
  const chartData = [...recentSessions].reverse().map((session) => ({
    date: format(parseISO(session.date), 'MMM d', { locale: appLocale() }),
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
    if (!trend) return <span className="text-app-muted text-xs">-</span>
    if (trend.isNeutral) return <Minus className="w-3 h-3 text-app-muted" />
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
          <Info className="mt-0.5 h-5 w-5 shrink-0 text-amber-400" aria-hidden="true" />
          <div>
            <p className="text-amber-400 text-sm font-semibold">No sessions in the last 7 days</p>
            <p className="text-amber-300/70 text-xs">Showing {weekLabel}</p>
          </div>
        </div>
      )}

      {/* Week Overview */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
        {/* Total Dives Card */}
        <div className="border border-app bg-app-panel rounded-xl p-3 sm:p-5 flex flex-col items-center justify-center text-center">
          <p className="text-app-accent text-xs font-semibold uppercase tracking-wider">{showWeekWarning ? 'Most recent week' : 'Last 7 days'}</p>
          <div className="mt-3 flex flex-col items-center">
            <p className="text-3xl sm:text-4xl font-bold text-app-text">{weekDives}</p>
            {weekDivesTrend && (
              <div className="mt-2 flex items-center justify-center gap-1.5">
                {weekDivesTrend.isPositive ? (
                  <TrendingUp className="w-4 h-4 text-green-400" />
                ) : weekDivesTrend.isNeutral ? (
                  <Minus className="w-4 h-4 text-app-muted" />
                ) : (
                  <TrendingDown className="w-4 h-4 text-red-400" />
                )}
                <span className="text-sm font-bold text-app-text">{weekDivesTrend.value}</span>
              </div>
            )}
          </div>
          <p className="text-app-accent text-xs mt-3">Total Dives {weekDivesTrend ? 'vs prev' : ''}</p>
        </div>

        {/* Performance Card */}
        <div className="border border-app bg-app-panel rounded-xl p-3 sm:p-5 flex flex-col items-center justify-center text-center">
          <p className="text-app-accent text-xs font-semibold uppercase tracking-wider">Avg Performance /10</p>
          <div className="mt-3 flex flex-col items-center">
            <p className={`text-3xl sm:text-4xl font-bold ${performanceColor(weekAvgPerf)}`}>
              {weekAvgPerf.toFixed(1)}
              <span className="ml-1 text-sm text-app-muted align-middle">/10</span>
            </p>
            {weekPerfTrend && (
              <div className="mt-2 flex items-center justify-center gap-1.5">
                {weekPerfTrend.isPositive ? (
                  <TrendingUp className="w-4 h-4 text-green-400" />
                ) : weekPerfTrend.isNeutral ? (
                  <Minus className="w-4 h-4 text-app-muted" />
                ) : (
                  <TrendingDown className="w-4 h-4 text-red-400" />
                )}
                <span className="text-sm font-bold text-app-text">{weekPerfTrend.percent}%</span>
              </div>
            )}
          </div>
          <p className="text-app-accent text-xs mt-3">Calibrated score {weekPerfTrend ? 'vs prev week' : ''}</p>
        </div>

        {/* Success Card */}
        <div className="border border-green-500/30 bg-app-panel rounded-xl p-3 sm:p-5 flex flex-col items-center justify-center text-center">
          <p className="text-green-400 text-xs font-semibold uppercase tracking-wider">Success</p>
          {recentSessions.length > 0 && (
            <div className="mt-3 flex flex-col items-center">
              <p className="text-3xl sm:text-4xl font-bold text-app-text">
                {(recentSessions[0].success_rate || 0).toFixed(0)}%
              </p>
              {successTrend && (
                <div className="mt-2 flex items-center justify-center gap-1.5">
                  {successTrend.isPositive ? (
                    <TrendingUp className="w-4 h-4 text-green-400" />
                  ) : successTrend.isNeutral ? (
                    <Minus className="w-4 h-4 text-app-muted" />
                  ) : (
                    <TrendingDown className="w-4 h-4 text-red-400" />
                  )}
                  <span className="text-sm font-bold text-app-text">{successTrend.percent}%</span>
                </div>
              )}
            </div>
          )}
          <p className="text-green-400 text-xs mt-3">Latest {successTrend ? 'vs prev' : ''}</p>
        </div>

        {/* Sessions Card */}
        <div className="border border-app bg-app-panel rounded-xl p-3 sm:p-5 flex flex-col items-center justify-center text-center">
          <p className="text-app-accent text-xs font-semibold uppercase tracking-wider">Sessions</p>
          <p className="text-3xl sm:text-4xl font-bold text-app-text mt-3">{recentSessions.length}</p>
        </div>
      </div>

      {/* Recent Sessions Cards */}
      <div className="space-y-3">
        <h3 className="text-lg font-semibold text-app-text flex items-center gap-2">
          <span className="w-2 h-2 bg-app-accent rounded-full"></span>
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
            let borderColor = 'border-app'
            borderColor = performanceBorder(session.avg_performance || 0)

            return (
              <button
                key={session.id}
                onClick={() => onSessionClick(session)}
                className={`bg-app-panel rounded-lg p-4 border ${borderColor} hover:border-app-accent transition text-left`}
              >
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <p className="text-app-text font-semibold text-sm">
                      {format(parseISO(session.date), 'MMM d', { locale: appLocale() })}
                    </p>
                    <p className="text-app-muted text-xs mt-1">
                      {session.total_dives} dives
                    </p>
                  </div>
                  {index === 0 && (
                    <span className="bg-app-accent-soft text-app-accent text-xs px-2 py-1 rounded">Latest</span>
                  )}
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-app-muted">Performance /10</span>
                    <div className="flex items-center gap-2">
                      <span className={`font-bold ${performanceColor(session.avg_performance || 0)}`}>
                        {session.avg_performance?.toFixed(1)}
                      </span>
                      <span className="text-xs text-app-muted">/10</span>
                      {perfTrend ? (
                        <div className="flex items-center gap-0.5">
                          {perfTrend.isPositive ? (
                            <TrendingUp className="w-4 h-4 text-green-400" />
                          ) : perfTrend.isNeutral ? (
                            <Minus className="w-4 h-4 text-app-muted" />
                          ) : (
                            <TrendingDown className="w-4 h-4 text-red-400" />
                          )}
                          <span className="text-xs font-semibold text-app-muted">{Math.abs(parseFloat(perfTrend.percent))}%</span>
                        </div>
                      ) : (
                        <span className="text-xs text-app-muted">-</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-app-muted">Success Rate</span>
                    <div className="flex items-center gap-2">
                      <span className="text-green-400 font-bold">{session.success_rate?.toFixed(0)}%</span>
                      {successTrend ? (
                        <div className="flex items-center gap-0.5">
                          {successTrend.isPositive ? (
                            <TrendingUp className="w-4 h-4 text-green-400" />
                          ) : successTrend.isNeutral ? (
                            <Minus className="w-4 h-4 text-app-muted" />
                          ) : (
                            <TrendingDown className="w-4 h-4 text-red-400" />
                          )}
                          <span className="text-xs font-semibold text-app-muted">{Math.abs(parseFloat(successTrend.percent))}%</span>
                        </div>
                      ) : (
                        <span className="text-xs text-app-muted">-</span>
                      )}
                    </div>
                  </div>
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
