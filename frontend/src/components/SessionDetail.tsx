import React, { useEffect, useState } from 'react'
import { X, TrendingUp, TrendingDown, Minus, Film } from 'lucide-react'
import { api } from '../services/api'
import { format, parseISO } from 'date-fns'
import {
  PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, LineChart, Line
} from 'recharts'
import DiveVideoPlayer from './DiveVideoPlayer'

interface Dive {
  id: number
  dive_code: string
  performance: string
  performance_numeric: number
  height: string
  dive_datetime: string
  session_id: number
  direction: number | null
  is_sync: boolean
  platform_type: string
  video_uuid?: string | null
}

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

interface SessionDetailProps {
  session: Session
  previousSession?: Session
  onClose: () => void
  allSessions: Session[]
}

const PERFORMANCE_CONFIG: { [key: string]: { label: string; color: string; bg: string; numeric: number } } = {
  P: { label: 'Perfect', color: 'text-green-400', bg: 'bg-green-500/20', numeric: 4 },
  G: { label: 'Good', color: 'text-blue-400', bg: 'bg-blue-500/20', numeric: 3 },
  M: { label: 'Medium', color: 'text-amber-400', bg: 'bg-amber-500/20', numeric: 2 },
  B: { label: 'Bad', color: 'text-orange-400', bg: 'bg-orange-500/20', numeric: 1 },
  F: { label: 'Failed', color: 'text-red-400', bg: 'bg-red-500/20', numeric: 0 },
}

const DIRECTION_NAMES: { [key: number]: string } = {
  1: 'Forward',
  2: 'Back',
  3: 'Reverse',
  4: 'Inward',
  5: 'Twist',
}

const DIRECTION_COLORS: { [key: number]: string } = {
  1: '#3b82f6',
  2: '#10b981',
  3: '#f59e0b',
  4: '#f97316',
  5: '#ec4899',
}

function SessionDetail({ session, previousSession, onClose, allSessions }: SessionDetailProps) {
  const [dives, setDives] = useState<Dive[]>([])
  const [previousDives, setPreviousDives] = useState<Dive[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedDive, setSelectedDive] = useState<Dive | null>(null)

  useEffect(() => {
    fetchSessionDives()
  }, [session.id])

  const fetchSessionDives = async () => {
    try {
      setLoading(true)
      const response = await api.get('/api/v1/dives', {
        params: { session_id: session.id, limit: 100 },
      })
      setDives(response.data || [])

      if (previousSession) {
        const prevResponse = await api.get('/api/v1/dives', {
          params: { session_id: previousSession.id, limit: 100 },
        })
        setPreviousDives(prevResponse.data || [])
      }
    } catch (err) {
      console.error('Error fetching dives:', err)
      setError('Failed to load session details')
    } finally {
      setLoading(false)
    }
  }

  // Calculate direction breakdown
  const directionBreakdown = dives.reduce((acc, dive) => {
    if (dive.direction) {
      const existing = acc.find(d => d.name === DIRECTION_NAMES[dive.direction!])
      if (existing) {
        existing.value += 1
      } else {
        acc.push({ name: DIRECTION_NAMES[dive.direction], value: 1 })
      }
    }
    return acc
  }, [] as Array<{ name: string; value: number }>)

  // Calculate height distribution
  const heightDistribution = dives.reduce((acc, dive) => {
    const existing = acc.find(d => d.name === dive.height)
    if (existing) {
      existing.value += 1
    } else {
      acc.push({ name: dive.height, value: 1 })
    }
    return acc
  }, [] as Array<{ name: string; value: number }>)

  // Performance flow over time
  const performanceFlow = dives.map((dive, index) => ({
    index: index + 1,
    performance: dive.performance_numeric,
    success: dive.performance_numeric >= 2 ? 1 : 0,
  }))

  // Calculate comparison metrics
  const calculateTrend = (current: number | undefined, previous: number | undefined) => {
    if (!current || !previous) return null
    const diff = current - previous
    return {
      value: Math.abs(diff),
      isPositive: diff > 0,
      isNeutral: diff === 0,
    }
  }

  const perfTrend = calculateTrend(session.avg_performance, previousSession?.avg_performance)
  const successTrend = calculateTrend(session.success_rate, previousSession?.success_rate)

  const TrendIndicator = ({ trend }: { trend: any }) => {
    if (!trend) return <span className="text-gray-500">-</span>
    if (trend.isNeutral) return <Minus className="w-4 h-4 text-gray-500" />
    return trend.isPositive
      ? <TrendingUp className="w-4 h-4 text-green-400" />
      : <TrendingDown className="w-4 h-4 text-red-400" />
  }

  return (
    <div className="fixed inset-0 bg-black/80 z-50 overflow-y-auto">
      <div className="min-h-screen flex items-center justify-center p-4">
        <div className="bg-gray-800 rounded-2xl border border-gray-700 max-w-4xl w-full max-h-[90vh] overflow-y-auto">
          {/* Header */}
          <div className="sticky top-0 bg-gray-800 border-b border-gray-700 p-6 flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-bold text-white">
                {format(parseISO(session.date), 'EEEE, MMMM d, yyyy')}
              </h2>
              <p className="text-gray-400 text-sm mt-1">
                {session.location || format(parseISO(session.date), 'EEEE')} • {dives.length} dives
              </p>
            </div>
            <button
              onClick={onClose}
              className="p-2 hover:bg-gray-700 rounded-lg transition"
            >
              <X className="w-6 h-6 text-gray-400" />
            </button>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-16">
              <div className="w-12 h-12 border-4 border-cyan-500 border-t-transparent rounded-full animate-spin"></div>
            </div>
          ) : error ? (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg m-6 p-4 text-red-400">
              {error}
            </div>
          ) : (
            <div className="p-6 space-y-8">
              {/* Session Stats Overview */}
              <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                <div className="bg-gray-700 rounded-lg p-4">
                  <p className="text-gray-400 text-xs uppercase">Total Dives</p>
                  <p className="text-2xl font-bold text-white mt-2">{session.total_dives}</p>
                </div>
                <div className="bg-gray-700 rounded-lg p-4">
                  <p className="text-gray-400 text-xs uppercase">Avg Performance</p>
                  <div className="flex items-center gap-2 mt-2">
                    <p className="text-2xl font-bold text-cyan-400">{session.avg_performance?.toFixed(2)}</p>
                    <TrendIndicator trend={perfTrend} />
                  </div>
                </div>
                <div className="bg-gray-700 rounded-lg p-4">
                  <p className="text-gray-400 text-xs uppercase">Success Rate</p>
                  <div className="flex items-center gap-2 mt-2">
                    <p className="text-2xl font-bold text-green-400">{session.success_rate?.toFixed(0)}%</p>
                    <TrendIndicator trend={successTrend} />
                  </div>
                </div>
                <div className="bg-gray-700 rounded-lg p-4">
                  <p className="text-gray-400 text-xs uppercase">Personal Dives</p>
                  <p className="text-2xl font-bold text-purple-400 mt-2">{session.total_personal_dives}</p>
                </div>
                <div className="bg-gray-700 rounded-lg p-4">
                  <p className="text-gray-400 text-xs uppercase">Best Dive</p>
                  <p className="text-xl font-bold text-yellow-400 mt-2">
                    {Math.max(...dives.map(d => d.performance_numeric)).toFixed(1)}
                  </p>
                </div>
              </div>

              {/* Dive Timeline & Video Player */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Dive Sequence (Left) */}
                <div className="lg:col-span-1">
                  <h3 className="text-xl font-semibold text-white mb-4">Dive Sequence</h3>
                  <div className="space-y-2 bg-gray-700/30 rounded-lg p-4 max-h-96 overflow-y-auto">
                    {dives.map((dive, index) => (
                      <button
                        key={dive.id}
                        onClick={() => setSelectedDive(dive)}
                        className={`w-full text-left flex items-center gap-3 pb-3 px-3 py-2 rounded-lg transition border-b border-gray-700 last:border-b-0 ${
                          selectedDive?.id === dive.id
                            ? 'bg-cyan-500/20 border-cyan-500/50'
                            : 'hover:bg-gray-600/20'
                        }`}
                      >
                        <div className="font-bold text-gray-500 min-w-6 text-sm">{index + 1}</div>
                        <div
                          className="w-3 h-3 rounded-full flex-shrink-0"
                          style={{ backgroundColor: dive.direction ? DIRECTION_COLORS[dive.direction] : '#6b7280' }}
                          title={dive.direction ? DIRECTION_NAMES[dive.direction] : 'Unknown'}
                        />
                        <div className="flex-1 min-w-0">
                          <span className="font-semibold text-white text-sm">{dive.dive_code}</span>
                          <span className="text-gray-400 mx-1.5">•</span>
                          <span className="text-xs text-gray-400">{dive.height}</span>
                          {dive.is_sync && <span className="text-xs bg-blue-500/20 text-blue-400 px-1.5 py-0.5 rounded ml-1">S</span>}
                        </div>
                        <div className="flex items-center gap-2">
                          {dive.video_uuid && (
                            <Film className="w-3.5 h-3.5 text-amber-400 flex-shrink-0" title="Video available" />
                          )}
                          <div className={`px-2 py-0.5 rounded text-xs font-semibold ${PERFORMANCE_CONFIG[dive.performance].bg}`}>
                            <span className={PERFORMANCE_CONFIG[dive.performance].color}>
                              {dive.performance}
                            </span>
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Video Player (Right) */}
                <div className="lg:col-span-2">
                  <h3 className="text-xl font-semibold text-white mb-4">Video Playback</h3>
                  <div className="bg-black rounded-lg overflow-hidden h-96 flex items-center justify-center">
                    {selectedDive && selectedDive.video_uuid ? (
                      <DiveVideoPlayer
                        diveCode={selectedDive.dive_code}
                        height={selectedDive.height}
                        videoUuid={selectedDive.video_uuid}
                        onClose={() => setSelectedDive(null)}
                      />
                    ) : (
                      <div className="text-center text-gray-400">
                        <Film className="w-12 h-12 mx-auto mb-3 opacity-50" />
                        <p className="text-sm">Click a dive with a 🎬 icon to play</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Analytics */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {/* Direction Breakdown */}
                <div className="bg-gray-700/30 rounded-lg p-4">
                  <h4 className="text-lg font-semibold text-white mb-4">Direction Breakdown</h4>
                  {directionBreakdown.length > 0 ? (
                    <ResponsiveContainer width="100%" height={200}>
                      <PieChart>
                        <Pie
                          data={directionBreakdown}
                          cx="50%"
                          cy="50%"
                          innerRadius={40}
                          outerRadius={70}
                          paddingAngle={2}
                          dataKey="value"
                        >
                          {directionBreakdown.map((entry, index) => {
                            const direction = Object.keys(DIRECTION_NAMES).find(
                              k => DIRECTION_NAMES[parseInt(k)] === entry.name
                            )
                            return <Cell key={`cell-${index}`} fill={direction ? DIRECTION_COLORS[parseInt(direction)] : '#6b7280'} />
                          })}
                        </Pie>
                        <Tooltip formatter={(value) => `${value} dives`} />
                      </PieChart>
                    </ResponsiveContainer>
                  ) : (
                    <p className="text-gray-500 text-center py-8">No direction data</p>
                  )}
                  <div className="mt-4 space-y-1 text-sm">
                    {directionBreakdown.map((dir) => (
                      <div key={dir.name} className="flex justify-between">
                        <span className="text-gray-400">{dir.name}</span>
                        <span className="text-white font-semibold">{dir.value} ({((dir.value / dives.length) * 100).toFixed(0)}%)</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Height Distribution */}
                <div className="bg-gray-700/30 rounded-lg p-4">
                  <h4 className="text-lg font-semibold text-white mb-4">Height Distribution</h4>
                  {heightDistribution.length > 0 ? (
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={heightDistribution}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#4b5563" />
                        <XAxis dataKey="name" stroke="#9ca3af" />
                        <YAxis stroke="#9ca3af" />
                        <Tooltip
                          contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151' }}
                          formatter={(value) => `${value} dives`}
                        />
                        <Bar dataKey="value" fill="#06b6d4" radius={[8, 8, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  ) : (
                    <p className="text-gray-500 text-center py-8">No height data</p>
                  )}
                </div>

                {/* Performance Flow */}
                <div className="bg-gray-700/30 rounded-lg p-4">
                  <h4 className="text-lg font-semibold text-white mb-4">Performance Flow</h4>
                  {performanceFlow.length > 0 ? (
                    <ResponsiveContainer width="100%" height={200}>
                      <LineChart data={performanceFlow}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#4b5563" />
                        <XAxis dataKey="index" stroke="#9ca3af" />
                        <YAxis domain={[0, 4]} stroke="#9ca3af" />
                        <Tooltip
                          contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151' }}
                          formatter={(value) => value.toFixed(1)}
                        />
                        <Line
                          type="monotone"
                          dataKey="performance"
                          stroke="#06b6d4"
                          strokeWidth={2}
                          dot={{ fill: '#06b6d4', r: 3 }}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  ) : (
                    <p className="text-gray-500 text-center py-8">No performance data</p>
                  )}
                </div>
              </div>

              {/* Comparison with Previous Session */}
              {previousSession && (
                <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4">
                  <h4 className="text-lg font-semibold text-white mb-4">Comparison with Previous Session</h4>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div>
                      <p className="text-gray-400 text-xs uppercase mb-2">Total Dives</p>
                      <div className="flex items-center gap-2">
                        <span className="text-white font-bold">{session.total_dives}</span>
                        <span className="text-gray-500 text-sm">vs {previousSession.total_dives}</span>
                        {session.total_dives > previousSession.total_dives && <TrendingUp className="w-4 h-4 text-green-400" />}
                        {session.total_dives < previousSession.total_dives && <TrendingDown className="w-4 h-4 text-red-400" />}
                      </div>
                    </div>
                    <div>
                      <p className="text-gray-400 text-xs uppercase mb-2">Avg Performance</p>
                      <div className="flex items-center gap-2">
                        <span className="text-cyan-400 font-bold">{session.avg_performance?.toFixed(2)}</span>
                        <span className="text-gray-500 text-sm">vs {previousSession.avg_performance?.toFixed(2)}</span>
                        {perfTrend && <TrendIndicator trend={perfTrend} />}
                      </div>
                    </div>
                    <div>
                      <p className="text-gray-400 text-xs uppercase mb-2">Success Rate</p>
                      <div className="flex items-center gap-2">
                        <span className="text-green-400 font-bold">{session.success_rate?.toFixed(0)}%</span>
                        <span className="text-gray-500 text-sm">vs {previousSession.success_rate?.toFixed(0)}%</span>
                        {successTrend && <TrendIndicator trend={successTrend} />}
                      </div>
                    </div>
                    {perfTrend && successTrend && (
                      <div>
                        <p className="text-gray-400 text-xs uppercase mb-2">Overall</p>
                        <p className="text-white font-bold">
                          {perfTrend.isPositive && successTrend.isPositive
                            ? '✨ Great Session!'
                            : perfTrend.isPositive || successTrend.isPositive
                            ? '→ Steady Progress'
                            : '💪 Keep Pushing'}
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Notes */}
              {session.notes && (
                <div className="bg-gray-700/30 rounded-lg p-4">
                  <h4 className="text-lg font-semibold text-white mb-2">Notes</h4>
                  <p className="text-gray-300">{session.notes}</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default SessionDetail
